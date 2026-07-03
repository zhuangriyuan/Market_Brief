"""
市场简报自动化脚本
------------------
用法:
    python main.py --mode daily     # 每日盘前简报
    python main.py --mode weekly    # 每周总结

流程:
    1. 抓取数据 (Finnhub 免费API: 财报日历、宏观日历、新闻)
    2. 尝试用 Gemini 免费API 生成带解析的版本
    3. 如果 Gemini 调用失败 (额度用完/网络问题/超时), 自动降级成"无AI模板版"
    4. 把结果发送到邮箱 + Discord

所有密钥都从环境变量读取, 不要把密钥写死在代码里。
本地测试时可以用 .env 文件 + python-dotenv, 或者直接 export 环境变量。
"""

import os
import sys
import json
import smtplib
import argparse
import datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

# ---------- 配置: 从环境变量读取, 不要硬编码 ----------
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

FINNHUB_BASE = "https://finnhub.io/api/v1"
FRED_BASE = "https://api.stlouisfed.org/fred/"

# 我们关心的官方宏观数据发布(用名字模糊匹配FRED的release列表, 不依赖硬编码release_id,
# 因为release_id记错的风险比较大, 用名字匹配更稳妥)
FRED_TARGET_RELEASES = [
    "Consumer Price Index",
    "Employment Situation",
    "Producer Price Index",
    "Gross Domestic Product",
    "Personal Income and Outlays",
    "Advance Monthly Sales for Retail and Food Services",
    "Employment Cost Index",
]

# 财报日历噪音过滤: 只保留这些"大家真的会关心"的大市值/知名公司,
# 可以根据自己的关注范围随时增删这个列表
MAJOR_TICKERS = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AVGO",
    "BRK.A", "BRK.B", "JPM", "V", "MA", "UNH", "XOM", "WMT", "PG", "JNJ",
    "HD", "COST", "ABBV", "MRK", "KO", "PEP", "BAC", "CVX", "DIS", "ADBE",
    "CRM", "NFLX", "AMD", "INTC", "QCOM", "TXN", "ORCL", "IBM", "CSCO",
    "PYPL", "NKE", "MCD", "SBUX", "BA", "CAT", "GE", "GS", "MS", "WFC",
    "C", "AXP", "DAL", "UAL", "AAL", "LUV", "UPS", "FDX", "T", "VZ",
    "TMO", "ABT", "PFE", "LLY", "BMY", "GILD", "AMGN", "COP", "SLB",
    "MU", "AMAT", "LRCX", "ASML", "TSM", "SPCX", "OPEN", "PLTR", "SNOW",
}


# ==================== 第一步: 抓数据 ====================

def fetch_earnings_calendar(days_ahead=7):
    """财报日历 (Finnhub 免费层), 过滤掉不常见的小盘股噪音"""
    today = dt.date.today()
    frm = today.isoformat()
    to = (today + dt.timedelta(days=days_ahead)).isoformat()
    try:
        r = requests.get(
            f"{FINNHUB_BASE}/calendar/earnings",
            params={"from": frm, "to": to, "token": FINNHUB_API_KEY},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json().get("earningsCalendar", [])
        major = [d for d in data if d.get("symbol") in MAJOR_TICKERS]
        if major:
            return major[:20]
        # 如果这周没有任何大市值公司报财报, 就退回全量列表(至少不是空的)
        return data[:10]
    except Exception as e:
        print(f"[warn] 财报日历抓取失败: {e}", file=sys.stderr)
        return []


def fetch_economic_calendar(days_ahead=7):
    """宏观经济日历: 改用FRED(圣路易斯联储)官方免费API, 比商业数据商更权威、更稳定"""
    if not FRED_API_KEY:
        print("[warn] 未配置 FRED_API_KEY, 跳过宏观日历", file=sys.stderr)
        return []
    try:
        # 第一步: 拿到所有release, 用名字模糊匹配出我们关心的那几个
        r = requests.get(
            FRED_BASE + "releases",
            params={"api_key": FRED_API_KEY, "file_type": "json"},
            timeout=15,
        )
        r.raise_for_status()
        releases = r.json().get("releases", [])
        matched = [
            rel for rel in releases
            if any(t.lower() in rel.get("name", "").lower() for t in FRED_TARGET_RELEASES)
        ]

        today = dt.date.today()
        to = today + dt.timedelta(days=days_ahead)
        events = []
        for rel in matched:
            rr = requests.get(
                FRED_BASE + "release/dates",
                params={
                    "release_id": rel["id"],
                    "api_key": FRED_API_KEY,
                    "file_type": "json",
                    "realtime_start": today.isoformat(),
                    "realtime_end": to.isoformat(),
                    # 必须加这个参数, 否则默认只返回"已经有数据"的历史发布日期, 不含未来日期
                    "include_release_dates_with_no_data": "true",
                },
                timeout=15,
            )
            rr.raise_for_status()
            for d in rr.json().get("release_dates", []):
                date_str = d.get("date", "")
                if today.isoformat() <= date_str <= to.isoformat():
                    events.append({"time": date_str, "event": rel["name"], "prev": "", "estimate": ""})

        events.sort(key=lambda x: x["time"])
        return events
    except Exception as e:
        print(f"[warn] 宏观日历抓取失败(FRED): {e}", file=sys.stderr)
        return []


def fetch_market_news(limit=15):
    """财经新闻 (Finnhub 免费层 general 分类)"""
    try:
        r = requests.get(
            f"{FINNHUB_BASE}/news",
            params={"category": "general", "token": FINNHUB_API_KEY},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        return data[:limit]
    except Exception as e:
        print(f"[warn] 新闻抓取失败: {e}", file=sys.stderr)
        return []


def gather_data(mode):
    days_ahead = 7 if mode == "weekly" else 1
    return {
        "earnings": fetch_earnings_calendar(days_ahead=7 if mode == "weekly" else 3),
        "economic": fetch_economic_calendar(days_ahead=7 if mode == "weekly" else 1),
        "news": fetch_market_news(limit=15),
        "mode": mode,
        "date": dt.date.today().isoformat(),
    }


# ==================== 第二步: AI 版本 (Gemini) ====================

def build_prompt(data):
    mode = data["mode"]
    news_text = "\n".join(
        f"- {n.get('headline','')} ({n.get('source','')})" for n in data["news"]
    )
    earnings_text = "\n".join(
        f"- {e.get('date')} {e.get('symbol')} 预期EPS {e.get('epsEstimate')}"
        for e in data["earnings"]
    )
    # 注意: FRED只提供官方发布日期, 不含市场预期/前值(那是商业数据商才有的),
    # 所以这里只给日期+数据名称, 预期解读交给AI基于数据本身的常识来写
    econ_text = "\n".join(
        f"- {e.get('time')} {e.get('event')}" for e in data["economic"]
    )

    if mode == "weekly":
        task = (
            "请生成《下周市场展望》中文简报, 包含: "
            "1) 本周市场总结 2) 下周重要宏观数据(含意义解读) "
            "3) 下周财报日历重点 4) 一句话总结。"
        )
    else:
        task = (
            "请生成《今日盘前简报》中文简报, 包含: "
            "1) 今日大事件 2) 今日最重要的新闻(每条一句话解析) "
            "3) 今日宏观数据看点 4) 今日重点财报。"
        )

    return f"""你是一名专业的美股财经编辑, 正在为一位中文读者撰写简报。
{task}

要求:
- 全部用中文
- 语言精炼, 不要废话, 不要"综上所述"这种套话
- 每条新闻/数据后面用一句话说明"为什么重要", 不要照抄原文
- 直接输出正文, 不要输出markdown代码块标记

原始数据如下:

【新闻标题】
{news_text or "(无数据)"}

【财报日历】
{earnings_text or "(无数据)"}

【宏观日历】
{econ_text or "(无数据)"}
"""


def call_gemini(prompt, timeout=30):
    """调用 Gemini API。失败时抛出异常, 由上层决定是否降级。"""
    if not GEMINI_API_KEY:
        raise RuntimeError("未配置 GEMINI_API_KEY")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2000},
    }
    r = requests.post(GEMINI_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    result = r.json()

    # 检查是否被安全过滤等原因拦截
    candidates = result.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini 未返回内容: {result}")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    if not text.strip():
        raise RuntimeError("Gemini 返回空内容")
    return text.strip()


def generate_ai_version(data):
    prompt = build_prompt(data)
    text = call_gemini(prompt)
    title = "📈 下周市场展望" if data["mode"] == "weekly" else "📈 今日盘前简报"
    return f"{title}（AI整理版 · {data['date']}）\n\n{text}"


# ==================== 第三步: 无AI模板版 (保底方案) ====================

def generate_raw_version(data):
    mode = data["mode"]
    title = "📋 下周市场展望" if mode == "weekly" else "📋 今日盘前简报"
    lines = [f"{title}（无AI模板版 · {data['date']}）", ""]
    lines.append("⚠️ 本条为AI服务不可用时的保底版本, 仅做原始数据罗列, 无解析。")
    lines.append("")

    lines.append("【新闻标题】")
    if data["news"]:
        for n in data["news"][:10]:
            src = n.get("source", "")
            headline = n.get("headline", "")
            lines.append(f"- {headline} [{src}]")
    else:
        lines.append("(暂无数据)")
    lines.append("")

    lines.append("【财报日历】")
    if data["earnings"]:
        for e in data["earnings"][:10]:
            lines.append(
                f"- {e.get('date')} {e.get('symbol')} 预期EPS {e.get('epsEstimate')}"
            )
    else:
        lines.append("(暂无数据)")
    lines.append("")

    lines.append("【宏观日历(数据来源: FRED官方)】")
    if data["economic"]:
        for e in data["economic"][:10]:
            lines.append(f"- {e.get('time')} {e.get('event')}")
    else:
        lines.append("(暂无数据)")

    return "\n".join(lines)


# ==================== 第四步: 生成最终内容 (带自动降级) ====================

def generate_content(data):
    """
    尝试生成AI版; 任何失败(额度用完/网络错误/超时/内容被拦截)
    都会被这里的 try/except 捕获, 自动降级成无AI模板版。
    """
    try:
        content = generate_ai_version(data)
        used_ai = True
    except Exception as e:
        print(f"[info] AI版生成失败, 自动降级为无AI版。原因: {e}", file=sys.stderr)
        content = generate_raw_version(data)
        used_ai = False
    return content, used_ai


# ==================== 第五步: 推送 ====================

def send_email(subject, body_text):
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD and EMAIL_TO):
        print("[warn] 邮件配置不完整, 跳过邮件发送", file=sys.stderr)
        return
    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [EMAIL_TO], msg.as_string())
    print("[ok] 邮件已发送")


def send_discord(content):
    if not DISCORD_WEBHOOK_URL:
        print("[warn] 未配置 Discord Webhook, 跳过Discord推送", file=sys.stderr)
        return
    # Discord 单条消息有2000字符限制, 超出的分段发送
    chunks = [content[i : i + 1900] for i in range(0, len(content), 1900)]
    for chunk in chunks:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=15)
        if r.status_code >= 300:
            print(f"[warn] Discord推送失败: {r.status_code} {r.text}", file=sys.stderr)
    print("[ok] Discord已推送")


# ==================== 主流程 ====================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "weekly"], required=True)
    args = parser.parse_args()

    print(f"[info] 开始生成 {args.mode} 简报...")
    data = gather_data(args.mode)
    content, used_ai = generate_content(data)

    tag = "AI版" if used_ai else "无AI降级版"
    subject_prefix = "下周市场展望" if args.mode == "weekly" else "今日盘前简报"
    subject = f"{subject_prefix} · {data['date']} [{tag}]"

    print("----- 生成内容预览 -----")
    print(content[:500])
    print("------------------------")

    send_email(subject, content)
    send_discord(content)


if __name__ == "__main__":
    main()
