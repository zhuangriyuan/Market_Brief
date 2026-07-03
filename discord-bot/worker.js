/**
 * Discord /stock 指令的处理服务, 跑在 Cloudflare Workers 上 (免费, 不需要一直挂机的服务器)。
 *
 * 流程:
 *   1. 收到 /stock ticker:AAPL 这样的指令
 *   2. 立刻回一个"占位"消息(DEFERRED), 因为Discord要求3秒内必须有响应,
 *      而"抓新闻 + 调AI翻译摘要"这两步加起来经常会超过3秒
 *   3. 后台(ctx.waitUntil)异步去抓Finnhub新闻, 再丢给Gemini整理成中文摘要
 *   4. 处理完之后, 用Discord的"编辑原始消息"接口把占位消息替换成真正的内容
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

    // ---- 验证请求确实来自Discord ----
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

        // 秒回占位消息, 真正的内容在后台处理完后异步编辑进去
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
      const summaryText = await summarizeNewsWithGemini(ticker, news, env.GEMINI_API_KEY);
      payload = {
        embeds: [
          {
            title: `📰 ${ticker} 最近新闻`,
            description: summaryText.slice(0, 4000),
            color: 0xf2a93c,
            footer: { text: "数据来源: Finnhub · 中文摘要: Gemini" },
          },
        ],
      };
    }
  } catch (err) {
    payload = { content: `抓取/整理 ${ticker} 的新闻失败: ${err.message}` };
  }

  await editOriginalInteractionResponse(env.DISCORD_APP_ID, interaction.token, payload);
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
  }));
}

async function summarizeNewsWithGemini(ticker, newsItems, geminiApiKey) {
  // 没配置Gemini key的话, 退回原始英文列表, 不报错(降级思路跟每日简报那边一致)
  if (!geminiApiKey) {
    return newsItems
      .map((n) => `**${n.headline}**\n${n.summary}\n[原文](${n.url}) · \`${n.source}\``)
      .join("\n\n");
  }

  const newsText = newsItems
    .map((n, i) => `${i + 1}. ${n.headline}\n${n.summary}`)
    .join("\n\n");

  const prompt = `你是财经编辑, 请把下面这些关于股票 ${ticker} 的英文新闻整理成中文。
每条格式固定为: "**中文标题翻译**" 换行 "一句话说明为什么重要", 每条之间空一行。
不要输出markdown代码块标记, 不要客套话, 直接给内容:

${newsText}`;

  const geminiUrl =
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${geminiApiKey}`;

  const res = await fetch(geminiUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0.4, maxOutputTokens: 1500 },
    }),
  });

  if (!res.ok) {
    throw new Error(`Gemini 返回状态码 ${res.status}`);
  }

  const data = await res.json();
  const text = (data.candidates?.[0]?.content?.parts || [])
    .map((p) => p.text || "")
    .join("");
  if (!text.trim()) {
    throw new Error("Gemini 返回空内容");
  }
  return text.trim();
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
