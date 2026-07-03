# 市场简报自动化 · 全免费方案

每天盘前 + 每周日晚, 自动抓数据 → AI整理(失败自动降级) → 发邮件 + Discord。
全程零成本, 用的都是免费额度。

## 你需要准备的 4 样东西 (都免费)

### 1. Finnhub API Key (数据源: 财报日历/宏观日历/新闻)
1. 打开 https://finnhub.io/register 注册
2. 登录后在 Dashboard 首页直接能看到你的 API Key, 复制下来
3. 免费额度: 60次/分钟, 完全够用

### 2. FRED API Key (数据源: 官方宏观经济日历, 免费)
1. 打开 https://fredaccount.stlouisfed.org/apikeys 注册/登录
2. 申请一个API Key(即时到账, 不需要审核)
3. 这是圣路易斯联储官方数据, 比商业数据商更权威, CPI/非农/PPI/GDP这些发布日期都从这里拿
4. 免费额度: 120次/分钟, 完全够用

### 3. Gemini API Key (AI整理)
1. 打开 https://aistudio.google.com/apikey
2. 用Google账号登录, 点 "Create API Key"
3. 复制生成的Key
4. 免费额度: 每天几百到上千次, 我们一天只用1-2次, 用不完

### 4. Gmail 应用专用密码 (发邮件用)
⚠️ 不能直接用你的Gmail登录密码, 要单独生成一个"应用专用密码":
1. 打开 https://myaccount.google.com/apppasswords
   (如果打不开, 先去 https://myaccount.google.com/security 把"两步验证"开启, 才能生成应用专用密码)
2. 生成一个新的应用密码, 名字随便填(比如"market-brief")
3. 会得到一串16位密码, 复制下来 —— 这个才是脚本要用的密码, 不是你平时登录用的密码

### 5. Discord Webhook URL (发Discord用)
1. 打开你想接收消息的Discord频道
2. 频道设置 → 整合(Integrations) → Webhook → 新建Webhook
3. 复制Webhook URL

## 部署步骤 (用GitHub Actions, 免费)

1. 把这个文件夹传到一个新的 GitHub 仓库 (私有仓库即可, 私有仓库GitHub Actions同样免费)
2. 进仓库 Settings → Secrets and variables → Actions → New repository secret,
   依次添加以下7个secret (名字必须完全一致):

   | Secret 名称 | 值 |
   |---|---|
   | `FINNHUB_API_KEY` | 第1步拿到的key |
   | `FRED_API_KEY` | 第2步拿到的key |
   | `GEMINI_API_KEY` | 第3步拿到的key |
   | `GMAIL_ADDRESS` | 你的Gmail邮箱地址 |
   | `GMAIL_APP_PASSWORD` | 第4步拿到的16位应用密码 |
   | `EMAIL_TO` | 你想接收简报的邮箱(可以跟发件邮箱一样) |
   | `DISCORD_WEBHOOK_URL` | 第5步拿到的webhook链接 |

3. 完成后, 去仓库的 Actions 标签页, 应该能看到两个工作流:
   "每日盘前简报" 和 "每周市场总结"
4. 先手动测试: 点进任意一个工作流, 右上角有个 "Run workflow" 按钮, 点一下立即触发,
   看看邮件和Discord有没有收到

## 关于定时时间

- 每日: 默认设置为 **8:30 ET (美东时间)**, 也就是开盘前1小时, 周一到周五
- 每周: 默认设置为 **周日 18:00 ET**

⚠️ 美国有夏令时, cron里的UTC时间需要每年切换两次:
- 夏令时(3月-11月, 现在): 用 `.yml` 文件里默认写的时间
- 冬令时(11月-3月): 每个时间都要 **+1小时**, 文件里已经用注释标好了怎么改

如果你不想每年手动改两次, 我也可以帮你把这块改成"自动判断夏令时"的逻辑, 需要的话告诉我。

## 本地测试 (可选, 建议先在自己电脑上跑通再部署)

```bash
pip install -r requirements.txt

export FINNHUB_API_KEY="xxx"
export FRED_API_KEY="xxx"
export GEMINI_API_KEY="xxx"
export GMAIL_ADDRESS="xxx@gmail.com"
export GMAIL_APP_PASSWORD="xxx"
export EMAIL_TO="xxx@gmail.com"
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/xxx"

python main.py --mode daily
```

终端会打印生成的内容预览, 同时发邮件+Discord。

## 当前版本的已知局限 (MVP, 后续可以迭代)

- **宏观日历已改用FRED官方API**: 覆盖CPI/非农/PPI/GDP/PCE/零售销售等核心数据的官方发布日期,
  但FRED只给"发布日期", 不含市场预期值/前值(那是商业数据商如Trading Economics才有的),
  简报里的"意义解读"是AI基于数据本身的常识写的, 不是基于具体预期数字的解读。
- **财报日历已加白名单过滤**: `MAJOR_TICKERS` 这个集合里维护了约80个大市值公司,
  只有这些公司的财报会被保留下来。你可以随时在 `main.py` 顶部增删这个列表,
  比如加你自己关注的股票代码。如果某周里这些公司都没有财报, 会自动退回显示全量列表(避免空白)。
- **新闻没有精细筛选**: 目前是抓Finnhub的general分类新闻取前几条, 不是专门筛选"最重要的10条",
  质量依赖Gemini整理时的判断。如果发现新闻不够聚焦, 可以调整 `fetch_market_news` 的筛选逻辑,
  比如改成只抓 category=company 或者叠加关键词过滤。
- **没有联储官员讲话日程**: 这个目前没有免费API能稳定覆盖, 需要的话可以另外抓Fed官网的讲话日历页面。

这些都不影响先跑起来看效果, 跑几天觉得哪块不准/不够用, 随时可以再调整对应的抓取函数。
