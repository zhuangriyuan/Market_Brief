"""
市场简报自动化脚本
------------------
用法:
    python main.py --mode daily     # 每日盘前简报
    python main.py --mode weekly    # 每周总结

流程:
    1. [夏令时保护] 判断"现在"是不是真的到了目标推送时间(纽约时间), 不是就直接退出
    2. 抓取数据 (Finnhub 免费API: 财报日历、新闻 / FRED 官方API: 宏观日历)
    3. 尝试用 Gemini 免费API 生成带解析的Markdown版本
    4. 如果 Gemini 调用失败 (额度用完/网络问题/超时), 自动降级成"无AI模板版"
    5. 把Markdown转成: (a) 好看的HTML网页, 写入 docs/ 目录, 供GitHub Pages发布
                        (b) HTML邮件正文 (不再是裸markdown符号)
                        (c) Discord embed (带颜色卡片, 而不是一堵纯文本墙)
    6. 分别推送到邮箱 + 对应的Discord频道 (盘前/周报是两个不同webhook)

所有密钥都从环境变量读取, 不要把密钥写死在代码里。
"""

import os
import sys
import smtplib
import argparse
import datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

import requests
import markdown as md

# ---------- 配置: 从环境变量读取, 不要硬编码 ----------
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")
DISCORD_WEBHOOK_DAILY = os.environ.get("DISCORD_WEBHOOK_DAILY", "")
DISCORD_WEBHOOK_WEEKLY = os.environ.get("DISCORD_WEBHOOK_WEEKLY", "")

# GitHub Pages 发布出来的网址前缀, 格式: https://<你的用户名>.github.io/<仓库名>
# 需要你在 README 里配置的地方填上自己的, 用于邮件/Discord里的"查看网页版"链接
PAGES_BASE_URL = os.environ.get("PAGES_BASE_URL", "")

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

FINNHUB_BASE = "https://finnhub.io/api/v1"
FRED_BASE = "https://api.stlouisfed.org/fred/"

FRED_TARGET_RELEASES = [
    "Consumer Price Index",
    "Employment Situation",
    "Producer Price Index",
    "Gross Domestic Product",
    "Personal Income and Outlays",
    "Advance Monthly Sales for Retail and Food Services",
    "Employment Cost Index",
]

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


# ==================== 第〇步: 夏令时保护 ====================

def is_scheduled_run():
    """区分'GitHub定时自动触发'还是'你自己手动点Run Workflow测试'"""
    return os.environ.get("GITHUB_EVENT_NAME") == "schedule"


def should_run_now(mode, tolerance_min=25):
    """
    workflow里对同一个任务配置了两个UTC触发时间点(分别对应夏令时/冬令时),
    这个函数用纽约时间(会自动处理夏令时切换)判断"现在"是不是真的到了目标时刻,
    不是的话说明这次触发是给另一个时区准备的, 直接跳过不做事。
    手动点 Run Workflow 测试时不受这个限制, 随时能跑。
    """
    now_et = dt.datetime.now(ZoneInfo("America/New_York"))
    if mode == "daily":
        if now_et.weekday() >= 5:  # 周六=5, 周日=6
            return False
        target = now_et.replace(hour=8, minute=30, second=0, microsecond=0)
    else:  # weekly, 目标是周日18:00 ET
        if now_et.weekday() != 6:
            return False
        target = now_et.replace(hour=18, minute=0, second=0, microsecond=0)
    diff_minutes = abs((now_et - target).total_seconds()) / 60
    return diff_minutes <= tolerance_min


# ==================== 第一步: 抓数据 ====================

def fetch_earnings_calendar(days_ahead=7):
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
        return major[:20] if major else data[:10]
    except Exception as e:
        print(f"[warn] 财报日历抓取失败: {e}", file=sys.stderr)
        return []


def fetch_economic_calendar(days_ahead=7):
    if not FRED_API_KEY:
        print("[warn] 未配置 FRED_API_KEY, 跳过宏观日历", file=sys.stderr)
        return []
    try:
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
                    "include_release_dates_with_no_data": "true",
                },
                timeout=15,
            )
            rr.raise_for_status()
            for d in rr.json().get("release_dates", []):
                date_str = d.get("date", "")
                if today.isoformat() <= date_str <= to.isoformat():
                    events.append({"time": date_str, "event": rel["name"]})

        events.sort(key=lambda x: x["time"])
        return events
    except Exception as e:
        print(f"[warn] 宏观日历抓取失败(FRED): {e}", file=sys.stderr)
        return []


def fetch_market_news(limit=15):
    try:
        r = requests.get(
            f"{FINNHUB_BASE}/news",
            params={"category": "general", "token": FINNHUB_API_KEY},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()[:limit]
    except Exception as e:
        print(f"[warn] 新闻抓取失败: {e}", file=sys.stderr)
        return []


def gather_data(mode):
    return {
        "earnings": fetch_earnings_calendar(days_ahead=7 if mode == "weekly" else 3),
        "economic": fetch_economic_calendar(days_ahead=7 if mode == "weekly" else 1),
        "news": fetch_market_news(limit=15),
        "mode": mode,
        "date": dt.date.today().isoformat(),
    }


# ==================== 第二步: AI 版本 (Gemini, 输出Markdown) ====================

def build_prompt(data):
    mode = data["mode"]
    news_text = "\n".join(
        f"- {n.get('headline','')} ({n.get('source','')})" for n in data["news"]
    )
    earnings_text = "\n".join(
        f"- {e.get('date')} {e.get('symbol')} 预期EPS {e.get('epsEstimate')}"
        for e in data["earnings"]
    )
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

格式要求:
- 全部用中文
- 用标准Markdown格式输出: 用 ## 做小标题, 用 - 做列表, 用 **文字** 做加粗
- 语言精炼, 不要废话, 不要"综上所述"这种套话
- 每条新闻/数据后面用一句话说明"为什么重要", 不要照抄原文
- 不要输出markdown代码块标记(不要用```包裹全文)

原始数据如下:

【新闻标题】
{news_text or "(无数据)"}

【财报日历】
{earnings_text or "(无数据)"}

【宏观日历】
{econ_text or "(无数据)"}
"""


def call_gemini(prompt, timeout=30):
    if not GEMINI_API_KEY:
        raise RuntimeError("未配置 GEMINI_API_KEY")
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2000},
    }
    r = requests.post(GEMINI_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    result = r.json()
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
    return text


# ==================== 第三步: 无AI模板版 (保底方案, 同样输出Markdown) ====================

def generate_raw_version(data):
    lines = ["> ⚠️ 本条为AI服务不可用时的保底版本, 仅做原始数据罗列, 无解析。", ""]

    lines.append("## 新闻标题")
    if data["news"]:
        for n in data["news"][:10]:
            lines.append(f"- {n.get('headline','')} `{n.get('source','')}`")
    else:
        lines.append("(暂无数据)")
    lines.append("")

    lines.append("## 财报日历")
    if data["earnings"]:
        for e in data["earnings"][:10]:
            lines.append(f"- {e.get('date')} **{e.get('symbol')}** 预期EPS {e.get('epsEstimate')}")
    else:
        lines.append("(暂无数据)")
    lines.append("")

    lines.append("## 宏观日历（数据来源: FRED官方）")
    if data["economic"]:
        for e in data["economic"][:10]:
            lines.append(f"- {e.get('time')} {e.get('event')}")
    else:
        lines.append("(暂无数据)")

    return "\n".join(lines)


def generate_content(data):
    try:
        content_md = generate_ai_version(data)
        used_ai = True
    except Exception as e:
        print(f"[info] AI版生成失败, 自动降级为无AI版。原因: {e}", file=sys.stderr)
        content_md = generate_raw_version(data)
        used_ai = False
    return content_md, used_ai


# ==================== 第四步: 渲染成三种输出格式 ====================

HTML_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body {{
    margin:0; padding:24px 16px 60px; background:#0b0f10; color:#e7e4db;
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    line-height:1.75;
  }}
  .wrap {{ max-width:720px; margin:0 auto; }}
  .eyebrow {{ font-size:12px; color:#f2a93c; letter-spacing:0.08em; margin-bottom:6px; }}
  h1 {{ font-size:22px; margin:0 0 18px; }}
  h2 {{ font-size:17px; color:#f2a93c; border-bottom:1px solid #232b2d; padding-bottom:6px; margin-top:28px; }}
  ul {{ padding-left:20px; }}
  li {{ margin-bottom:8px; font-size:14.5px; }}
  strong {{ color:#fff; }}
  code {{ background:#161d1f; padding:1px 6px; border-radius:4px; font-size:12px; color:#8b9296; }}
  blockquote {{ border-left:3px solid #f2a93c; margin:0; padding:8px 14px; background:#161d1f; border-radius:6px; color:#f2a93c; font-size:13px; }}
  .footer {{ margin-top:40px; font-size:11.5px; color:#8b9296; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">市场简报 · {date}</div>
  <h1>{title}</h1>
  {body}
  <div class="footer">{footer}</div>
</div>
</body>
</html>
"""


def render_html_page(content_md, data, used_ai):
    title = "下周市场展望" if data["mode"] == "weekly" else "今日盘前简报"
    tag = "AI整理版" if used_ai else "无AI降级版"
    body_html = md.markdown(content_md, extensions=["extra"])
    footer = f"生成方式: {tag} ｜ 数据来源: Finnhub / FRED"
    return HTML_PAGE_TEMPLATE.format(
        title=f"{title}［{tag}］", date=data["date"], body=body_html, footer=footer
    )


EMAIL_TEMPLATE = """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f2f2f2;">
<div style="max-width:640px;margin:0 auto;background:#ffffff;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:#222;">
  <div style="background:#111418;padding:20px 24px;">
    <div style="color:#f2a93c;font-size:12px;letter-spacing:0.08em;">市场简报 · {date}</div>
    <div style="color:#fff;font-size:20px;font-weight:600;margin-top:4px;">{title}</div>
  </div>
  <div style="padding:20px 24px;font-size:14.5px;line-height:1.8;">
    {body}
  </div>
  {pages_link}
  <div style="padding:14px 24px;color:#999;font-size:11.5px;border-top:1px solid #eee;">
    生成方式: {tag} ｜ 数据来源: Finnhub / FRED ｜ 本邮件由自动化脚本发送
  </div>
</div>
</body></html>
"""


def render_email_html(content_md, data, used_ai, page_url=None):
    title = "下周市场展望" if data["mode"] == "weekly" else "今日盘前简报"
    tag = "AI整理版" if used_ai else "无AI降级版"
    body_html = md.markdown(content_md, extensions=["extra"])
    # 邮件里h2标签换个更保守的行内样式, 部分邮箱客户端会吃掉<style>标签里的样式
    body_html = body_html.replace(
        "<h2>", '<h2 style="font-size:15px;color:#c9820f;border-bottom:1px solid #eee;padding-bottom:6px;margin-top:22px;">'
    ).replace("<ul>", '<ul style="padding-left:20px;">').replace(
        "<blockquote>",
        '<blockquote style="border-left:3px solid #f2a93c;margin:0;padding:8px 14px;background:#fff8ec;border-radius:6px;color:#a35b00;font-size:13px;">',
    )
    pages_link = ""
    if page_url:
        pages_link = f"""<div style="padding:0 24px 20px;">
          <a href="{page_url}" style="display:inline-block;background:#f2a93c;color:#1a1200;text-decoration:none;padding:9px 16px;border-radius:8px;font-size:13px;font-weight:600;">在网页中查看好看的版本 →</a>
        </div>"""
    return EMAIL_TEMPLATE.format(
        date=data["date"], title=f"{title}［{tag}］", body=body_html,
        tag=tag, pages_link=pages_link,
    )


def save_html_page(html_content, mode):
    """写入 docs/ 目录, 交给 GitHub Pages 发布。同时保留一份带日期的存档。"""
    os.makedirs("docs", exist_ok=True)

    # 关键: 没有这个文件, GitHub Pages 会默认尝试用 Jekyll 构建 docs/ 目录,
    # 但我们放的是纯HTML文件不是Jekyll项目结构, 会导致构建报错(SCSS找不到之类)。
    # 加这个空文件告诉GitHub Pages "别用Jekyll处理, 原样发布静态文件就行"。
    nojekyll_path = "docs/.nojekyll"
    if not os.path.exists(nojekyll_path):
        open(nojekyll_path, "w").close()

    today = dt.date.today().isoformat()
    stable_name = f"docs/{mode}.html"          # 固定链接, 永远是"最新一期"
    archive_name = f"docs/{mode}-{today}.html"  # 带日期的存档, 方便回看历史
    for path in (stable_name, archive_name):
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)
    return stable_name


# ==================== 第五步: 推送 ====================

def send_email(subject, html_body):
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD and EMAIL_TO):
        print("[warn] 邮件配置不完整, 跳过邮件发送", file=sys.stderr)
        return
    msg = MIMEMultipart("alternative")
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [EMAIL_TO], msg.as_string())
    print("[ok] 邮件已发送")


def send_discord(content_md, data, used_ai, page_url=None):
    webhook = DISCORD_WEBHOOK_WEEKLY if data["mode"] == "weekly" else DISCORD_WEBHOOK_DAILY
    if not webhook:
        print("[warn] 未配置对应的 Discord Webhook, 跳过Discord推送", file=sys.stderr)
        return

    title = "📈 下周市场展望" if data["mode"] == "weekly" else "📈 今日盘前简报"
    tag = "AI整理版" if used_ai else "无AI降级版"
    color = 0xF2A93C if used_ai else 0x8B9296

    # Discord embed description 上限4096字符, 超出的话截断并引导去网页版看完整内容
    desc = content_md
    truncated = len(desc) > 3900
    if truncated:
        desc = desc[:3900] + "\n\n…（内容较长，完整版见下方链接）"

    embed = {
        "title": f"{title} ［{tag}］",
        "description": desc,
        "color": color,
        "footer": {"text": f"{data['date']} · Finnhub / FRED"},
    }
    if page_url:
        embed["url"] = page_url  # 点标题直接跳转到网页版

    r = requests.post(webhook, json={"embeds": [embed]}, timeout=15)
    if r.status_code >= 300:
        print(f"[warn] Discord推送失败: {r.status_code} {r.text}", file=sys.stderr)
    else:
        print("[ok] Discord已推送")


# ==================== 主流程 ====================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "weekly"], required=True)
    args = parser.parse_args()

    if is_scheduled_run() and not should_run_now(args.mode):
        print("[info] 当前不是目标推送时间(夏令时/冬令时双保险cron的另一个触发点), 跳过本次运行。")
        return

    print(f"[info] 开始生成 {args.mode} 简报...")
    data = gather_data(args.mode)
    content_md, used_ai = generate_content(data)

    html_page = render_html_page(content_md, data, used_ai)
    page_path = save_html_page(html_page, args.mode)

    page_url = None
    if PAGES_BASE_URL:
        page_url = f"{PAGES_BASE_URL.rstrip('/')}/{args.mode}.html"

    tag = "AI版" if used_ai else "无AI降级版"
    subject_prefix = "下周市场展望" if args.mode == "weekly" else "今日盘前简报"
    subject = f"{subject_prefix} · {data['date']} [{tag}]"

    email_html = render_email_html(content_md, data, used_ai, page_url=page_url)

    print("----- 生成内容预览(前300字) -----")
    print(content_md[:300])
    print(f"[info] 网页版已写入: {page_path}")
    print("----------------------------------")

    send_email(subject, email_html)
    send_discord(content_md, data, used_ai, page_url=page_url)


if __name__ == "__main__":
    main()
