/**
 * Discord /stock 指令的处理服务, 跑在 Cloudflare Workers 上 (免费, 不需要一直挂机的服务器)。
 *
 * 工作原理:
 *   Discord 不需要一个"一直连着"的机器人进程就能支持斜杠指令,
 *   它会把用户在频道里打的指令, 通过HTTP POST发到你配置的"Interactions Endpoint URL",
 *   这个Worker就是接那个请求的地方, 处理完直接HTTP返回结果, 用完即走, 完全免费。
 *
 * 指令: /stock ticker:AAPL  →  返回该股票最近一周的新闻标题
 */

import { verifyKey } from "discord-interactions";

const INTERACTION_TYPE = { PING: 1, APPLICATION_COMMAND: 2 };
const RESPONSE_TYPE = { PONG: 1, CHANNEL_MESSAGE_WITH_SOURCE: 4 };

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Market Brief Discord Bot is running.", { status: 200 });
    }

    // ---- 第一步: 验证请求确实来自Discord (防止别人伪造请求调用你的Worker) ----
    // 按Discord官方教程的写法: 验证用原始字节(ArrayBuffer), 解析JSON时再单独读一次body,
    // 这样能避免文本编码方式不一致导致验证失败的问题。
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

    // ---- 第二步: Discord 会先发一个 PING 来验证你的endpoint是否正常, 必须秒回 PONG ----
    if (interaction.type === INTERACTION_TYPE.PING) {
      return jsonResponse({ type: RESPONSE_TYPE.PONG });
    }

    // ---- 第三步: 处理真正的指令 ----
    if (interaction.type === INTERACTION_TYPE.APPLICATION_COMMAND) {
      const commandName = interaction.data?.name;

      if (commandName === "stock") {
        const tickerOption = interaction.data.options?.find((o) => o.name === "ticker");
        const ticker = (tickerOption?.value || "").toUpperCase().trim();

        if (!ticker) {
          return jsonResponse(replyText("请提供股票代码, 例如 `/stock ticker:AAPL`"));
        }

        try {
          const news = await fetchStockNews(ticker, env.FINNHUB_API_KEY);
          return jsonResponse(replyNewsEmbed(ticker, news));
        } catch (err) {
          return jsonResponse(replyText(`抓取 ${ticker} 的新闻失败: ${err.message}`));
        }
      }

      return jsonResponse(replyText("未知指令。"));
    }

    return new Response("未处理的交互类型", { status: 400 });
  },
};

// ==================== 工具函数 ====================

function jsonResponse(obj) {
  return new Response(JSON.stringify(obj), {
    headers: { "Content-Type": "application/json" },
  });
}

function replyText(text) {
  return { type: RESPONSE_TYPE.CHANNEL_MESSAGE_WITH_SOURCE, data: { content: text } };
}

function replyNewsEmbed(ticker, newsItems) {
  if (!newsItems.length) {
    return replyText(`没查到 ${ticker} 最近一周的新闻, 换个代码试试？`);
  }
  const description = newsItems
    .map((n) => `**${n.headline}**\n${n.summary}\n[查看原文](${n.url}) · \`${n.source}\``)
    .join("\n\n")
    .slice(0, 4000);

  return {
    type: RESPONSE_TYPE.CHANNEL_MESSAGE_WITH_SOURCE,
    data: {
      embeds: [
        {
          title: `📰 ${ticker} 最近新闻`,
          description,
          color: 0xf2a93c,
          footer: { text: "数据来源: Finnhub" },
        },
      ],
    },
  };
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
    summary: n.summary ? n.summary.slice(0, 120) + (n.summary.length > 120 ? "…" : "") : "",
    url: n.url || "",
    source: n.source || "",
  }));
}
