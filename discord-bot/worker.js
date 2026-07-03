/**
 * Discord /stock 指令的处理服务, 跑在 Cloudflare Workers 上 (免费, 不需要一直挂机的服务器)。
 *
 * 流程:
 *   1. 收到 /stock ticker:AAPL 这样的指令
 *   2. 立刻回一个"占位"消息(DEFERRED), 因为Discord要求3秒内必须有响应
 *   3. 后台(ctx.waitUntil)异步去抓Finnhub新闻, 再丢给Gemini把标题翻译成中文+写一句话原因
 *   4. 日期和原文链接直接用Finnhub返回的原始数据拼接, 不经过AI处理(AI容易把链接写错/写丢,
 *      日期/链接这种精确信息交给代码直接拼更可靠, AI只负责"翻译"和"总结"这种需要语言能力的部分)
 *   5. 处理完之后, 用Discord的"编辑原始消息"接口把占位消息替换成真正的内容
 */

import { verifyKey } from "discord-interactions";

const INTERACTION_TYPE = { PING: 1, APPLICATION_COMMAND: 2 };
const RESPONSE_TYPE = {
  PONG: 1,
  CHANNEL_MESSAGE_WITH_SOURCE: 4,
  DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE: 5,
};

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("Market Brief Discord Bot is running.", { status: 200 });
    }

    const signature = request.headers.get("X-Signature-Ed25519");
    const timestamp = request.headers.get("X-Signature-Timestamp");
    const bodyBuffer = await request.clone().arrayBuffer();

    const isValid =
      signature &&
      timestamp &&
      (await verifyKey(bodyBuffer, signature, timestamp, env.DISCORD_PUBLIC_KEY));

    if (!isValid) {
      return new Response("Bad request signature.", { status: 401 });
    }

    const interaction = await request.json();

    if (interaction.type === INTERACTION_TYPE.PING) {
      return jsonResponse({ type: RESPONSE_TYPE.PONG });
    }

    if (interaction.type === INTERACTION_TYPE.APPLICATION_COMMAND) {
      const commandName = interaction.data?.name;

      if (commandName === "stock") {
        const tickerOption = interaction.data.options?.find((o) => o.name === "ticker");
        const ticker = (tickerOption?.value || "").toUpperCase().trim();

        if (!ticker) {
          return jsonResponse(replyText("请提供股票代码, 例如 `/stock ticker:AAPL`"));
        }

        ctx.waitUntil(handleStockCommand(ticker, interaction, env));
        return jsonResponse({ type: RESPONSE_TYPE.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE });
      }

      return jsonResponse(replyText("未知指令。"));
    }

    return new Response("未处理的交互类型", { status: 400 });
  },
};

// ==================== 后台处理逻辑 ====================

async function handleStockCommand(ticker, interaction, env) {
  let payload;
  try {
    const news = await fetchStockNews(ticker, env.FINNHUB_API_KEY);
    if (!news.length) {
      payload = { content: `没查到 ${ticker} 最近一周的新闻, 换个代码试试？` };
    } else {
      let translated = null;
      try {
        translated = await translateHeadlines(ticker, news, env.GEMINI_API_KEY);
      } catch (e) {
        console.error("Gemini翻译失败, 改用原始英文:", e.message);
      }

      const description = news
        .map((n, i) => formatNewsItem(n, translated ? translated[i] : null))
        .join("\n\n")
        .slice(0, 4000);

      payload = {
        embeds: [
          {
            title: `📰 ${ticker} 最近新闻`,
            description,
            color: 0xf2a93c,
            footer: { text: translated ? "数据来源: Finnhub · 中文摘要: Gemini" : "数据来源: Finnhub" },
          },
        ],
      };
    }
  } catch (err) {
    payload = { content: `抓取/整理 ${ticker} 的新闻失败: ${err.message}` };
  }

  await editOriginalInteractionResponse(env.DISCORD_APP_ID, interaction.token, payload);
}

// 拼装每条新闻的最终展示格式: 标题+原因来自AI翻译(或原始英文兜底), 日期和链接永远来自Finnhub原始数据
function formatNewsItem(newsRaw, translatedLine) {
  let zhTitle = newsRaw.headline;
  let zhReason = newsRaw.summary;

  if (translatedLine) {
    const parts = translatedLine.split("::");
    if (parts[0]?.trim()) zhTitle = parts[0].trim();
    if (parts[1]?.trim()) zhReason = parts[1].trim();
  }

  const metaParts = [`[查看原文](${newsRaw.url})`];
  if (newsRaw.date) metaParts.push(newsRaw.date);
  if (newsRaw.source) metaParts.push(`\`${newsRaw.source}\``);

  return `**${zhTitle}**\n${zhReason}\n${metaParts.join(" · ")}`;
}

async function editOriginalInteractionResponse(appId, interactionToken, payload) {
  const url = `https://discord.com/api/v10/webhooks/${appId}/${interactionToken}/messages/@original`;
  const res = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    console.error("编辑原始消息失败:", res.status, await res.text());
  }
}

async function fetchStockNews(ticker, finnhubApiKey) {
  const to = new Date();
  const from = new Date(to.getTime() - 7 * 24 * 60 * 60 * 1000);
  const fmt = (d) => d.toISOString().slice(0, 10);

  const url =
    `https://finnhub.io/api/v1/company-news?symbol=${encodeURIComponent(ticker)}` +
    `&from=${fmt(from)}&to=${fmt(to)}&token=${finnhubApiKey}`;

  const res = await fetch(url);
  if (!res.ok) throw new Error(`Finnhub 返回状态码 ${res.status}`);

  const data = await res.json();
  return data.slice(0, 5).map((n) => ({
    headline: n.headline || "(无标题)",
    summary: n.summary || "",
    url: n.url || "",
    source: n.source || "",
    // Finnhub的datetime是Unix秒级时间戳, 转成 YYYY-MM-DD
    date: n.datetime ? new Date(n.datetime * 1000).toISOString().slice(0, 10) : "",
  }));
}

// 让Gemini严格按 "中文标题::一句话原因" 逐行输出, 一条新闻一行,
// 这样才能在代码里可靠地拆出标题和原因, 分别重新拼接日期/链接, 不依赖AI自己把链接写对。
async function translateHeadlines(ticker, newsItems, geminiApiKey) {
  if (!geminiApiKey) return null;

  const listText = newsItems
    .map((n, i) => `${i + 1}. ${n.headline}\n${n.summary}`)
    .join("\n\n");

  const prompt = `你是财经编辑。请把下面这 ${newsItems.length} 条关于股票 ${ticker} 的英文新闻,
按原有顺序逐条翻译整理, 严格按以下格式输出, 一条新闻一行, 用"::"分隔, 不要有其他任何内容:
中文标题翻译::一句话说明为什么重要

新闻原文:
${listText}`;

  const geminiUrl =
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${geminiApiKey}`;

  const res = await fetch(geminiUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0.4, maxOutputTokens: 2000 },
    }),
  });

  if (!res.ok) throw new Error(`Gemini 返回状态码 ${res.status}`);

  const data = await res.json();
  const candidate = data.candidates?.[0];
  if (candidate?.finishReason === "MAX_TOKENS") {
    console.error("Gemini输出触顶被截断了, 可以考虑再调大maxOutputTokens");
  }
  const text = (candidate?.content?.parts || []).map((p) => p.text || "").join("");
  if (!text.trim()) throw new Error("Gemini 返回空内容");

  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.includes("::"));

  // 数量对不上说明AI没有严格按格式输出, 放弃翻译结果, 让调用方退回原始英文兜底
  if (lines.length !== newsItems.length) {
    console.error(`翻译行数(${lines.length})与新闻条数(${newsItems.length})不匹配, 退回原始英文`);
    return null;
  }
  return lines;
}

// ==================== 工具函数 ====================

function jsonResponse(obj) {
  return new Response(JSON.stringify(obj), {
    headers: { "Content-Type": "application/json" },
  });
}

function replyText(text) {
  return { type: RESPONSE_TYPE.CHANNEL_MESSAGE_WITH_SOURCE, data: { content: text } };
}
