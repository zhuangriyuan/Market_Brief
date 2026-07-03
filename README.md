# 市场简报自动化 · 全免费方案

每天盘前 + 每周日晚, 自动抓数据 → AI整理(失败自动降级) → 发邮件(HTML富文本) + 发Discord(分频道)。
另外还有一个可选的Discord `/stock` 查询指令(在 `discord-bot/` 文件夹, 单独部署)。
全程零成本, 用的都是免费额度, 部署完之后不需要你的电脑一直开着——所有东西都跑在云端
(GitHub Actions + Cloudflare Workers), 跟你的电脑没有任何关系, 关机/换电脑都不影响运行。

## 这套东西是不是一直免费、不用管？

| 环节 | 免费程度 |
|---|---|
| GitHub Actions | 私有仓库每月2000分钟免费额度, 这套脚本一天用不到几分钟, 长期免费 |
| Cloudflare Workers | 每天10万次请求免费, 个人用量不可能触顶, 长期免费 |
| Finnhub / FRED / Gmail SMTP / GitHub Pages | 个人使用场景下都是长期免费 |
| **Gemini API 免费层** | ⚠️ 唯一不能打包票"永远不变"的一环。Google 2025年底砍过一次免费额度, 目前用量远低于限额不受影响, 但这是"目前免费"不是"合同保证"。真被大幅收紧的话, 你会在邮件/Discord标题看到"无AI降级版"字样, 那就是信号, 到时候可以换一个备用免费API(比如DeepSeek/OpenRouter) |

结论: **目前全免费, 部署完基本不用管。** 唯一需要偶尔留意的是Gemini免费额度这一项。

## 你需要准备的东西 (都免费)

### 1. Finnhub API Key (数据源: 财报日历/新闻)
1. 打开 https://finnhub.io/register 注册
2. 登录后在 Dashboard 首页直接能看到你的 API Key
3. 免费额度: 60次/分钟, 完全够用

### 2. FRED API Key (数据源: 官方宏观经济日历)
1. 打开 https://fredaccount.stlouisfed.org/apikeys 注册/登录
2. 申请一个API Key(即时到账, 不需要审核)
3. 圣路易斯联储官方数据, CPI/非农/PPI/GDP这些发布日期都从这里拿
4. 免费额度: 120次/分钟

### 3. Gemini API Key (AI整理)
1. 打开 https://aistudio.google.com/apikey
2. 用Google账号登录, 点 "Create API Key"
3. 免费额度: 每天几百到上千次, 我们一天只用1-2次, 用不完

### 4. Gmail 应用专用密码 (发邮件用)
⚠️ 不能直接用你的Gmail登录密码, 要单独生成一个"应用专用密码":
1. 打开 https://myaccount.google.com/apppasswords
   (如果打不开, 先去 https://myaccount.google.com/security 把"两步验证"开启)
2. 生成一个新的应用密码, 名字随便填
3. 得到一串16位密码 —— 这个才是脚本要用的, 不是你平时登录用的密码

### 5. 两个 Discord Webhook (分别对应两个频道)
1. 打开你想接收"每日盘前简报"的频道 → 频道设置 → 整合(Integrations) → Webhook → 新建, 复制URL
2. 打开你想接收"每周市场展望"的另一个频道 → 同样操作, 再复制一个URL

## 部署步骤

1. 把这个文件夹传到一个新的 GitHub 仓库(私有仓库即可)
2. 进仓库 Settings → Secrets and variables → Actions → New repository secret,
   依次添加以下8个secret(名字必须完全一致):

   | Secret 名称 | 值 |
   |---|---|
   | `FINNHUB_API_KEY` | 第1步拿到的key |
   | `FRED_API_KEY` | 第2步拿到的key |
   | `GEMINI_API_KEY` | 第3步拿到的key |
   | `GMAIL_ADDRESS` | 你的Gmail邮箱地址 |
   | `GMAIL_APP_PASSWORD` | 第4步拿到的16位应用密码 |
   | `EMAIL_TO` | 你想接收简报的邮箱 |
   | `DISCORD_WEBHOOK_DAILY` | 第5步"每日盘前简报"频道的webhook |
   | `DISCORD_WEBHOOK_WEEKLY` | 第5步"每周市场展望"频道的webhook |

3. 完成后, 去仓库的 Actions 标签页, 应该能看到三个工作流:
   "每日盘前简报"、"每周市场总结"、"仓库保活"
4. 手动测试: 点进任意一个工作流, 右上角 "Run workflow" 按钮点一下立即触发,
   邮件/Discord 都能收到就说明配置对了(手动触发不受时间限制, 随时能测)

## 网页版预览 (GitHub Pages)

Discord和邮件都没法真正内嵌一个有CSS样式的自定义网页, 所以做法是:
脚本每次运行都会生成一个好看的HTML页面, 存进仓库的 `docs/` 目录, 用 GitHub Pages 免费托管,
邮件正文最下面和Discord卡片标题都会带一个链接, 点开就是网页版。

开启步骤(只需要设置一次):
1. 仓库 Settings → Pages
2. Source 选择 "Deploy from a branch", Branch 选择 `main`, 文件夹选择 `/docs`, 保存
3. 稍等一两分钟, GitHub会给你一个网址, 格式是 `https://<你的GitHub用户名>.github.io/<仓库名>`
4. 回到 Settings → Secrets and variables → Actions → 切到 "Variables" 标签(不是Secrets),
   新建一个 repository variable: 名称 `PAGES_BASE_URL`, 值填第3步的网址(结尾不要带斜杠)
5. 之后每次简报都有稳定链接: `.../daily.html`(每日最新)、`.../weekly.html`(每周最新),
   另外还会存带日期的存档比如 `daily-2026-07-06.html`, 方便回看历史

⚠️ **踩过的坑**: 第一次开启Pages时, GitHub默认会用Jekyll(一套静态网站生成器)去"构建"
`docs/`目录, 但我们放的是纯HTML文件不是Jekyll项目结构, 会报错(类似
`No such file or directory @ dir_chdir0 - /github/workspace/docs` 或SCSS相关报错)。
**解决办法**: 确保 `docs/` 目录里有一个空文件 `.nojekyll`, 告诉GitHub Pages
"别用Jekyll处理, 原样发布静态文件就行"。这版代码已经会自动创建这个文件,
但如果你是在这个修复之前就开启过Pages, 报错已经发生过一次, 需要手动补一次:
去仓库网页 "Add file" → "Create new file", 文件名输入 `docs/.nojekyll`(会自动建好docs文件夹),
内容留空, 直接commit, 这样会触发一次新的构建, 就不会再报错了。

## 关于定时时间 (已支持自动判断夏令时)

- 每日: 目标 **8:30 ET (美东时间)**, 周一到周五
- 每周: 目标 **周日 18:00 ET**

`.yml` 文件里给每个任务配置了两个UTC触发时间点(分别对应夏令时EDT和冬令时EST),
脚本内部用 `zoneinfo` 库读取真实的纽约时间, 自动判断"现在是不是真的到了目标时刻",
不是的话直接跳过不做事。全年不需要你手动改cron表达式。

## 仓库保活 (防止定时任务被GitHub自动暂停)

GitHub 规定: 一个仓库如果连续 **60天没有任何提交**, 里面所有的定时任务(cron)会被自动暂停,
需要你手动去 Actions 页面重新启用。

实际上每日/每周简报只要跑成功, 通常都会顺带commit一次(生成的网页内容变了),
天然就会保持仓库活跃, 但为了保险, 额外加了一个 `keepalive.yml` 工作流,
**每月1号自动提交一次**(哪怕前面两个任务因为什么原因全都没触发成功也没关系),
确保永远不会碰到60天这条线。这个任务不需要你做任何配置, 部署完就自动生效。

## 本地测试 (可选)

```bash
pip install -r requirements.txt

export FINNHUB_API_KEY="xxx"
export FRED_API_KEY="xxx"
export GEMINI_API_KEY="xxx"
export GMAIL_ADDRESS="xxx@gmail.com"
export GMAIL_APP_PASSWORD="xxx"
export EMAIL_TO="xxx@gmail.com"
export DISCORD_WEBHOOK_DAILY="https://discord.com/api/webhooks/xxx"
export DISCORD_WEBHOOK_WEEKLY="https://discord.com/api/webhooks/yyy"
export PAGES_BASE_URL="https://你的用户名.github.io/仓库名"   # 可选

python main.py --mode daily
```

⚠️ **Windows用户注意**: 上面的 `export` 命令是Mac/Linux(bash)的语法, Windows不通用:
- **CMD(命令提示符)**, 提示符长得像 `C:\Users\你的名字>`: 用 `set 变量名=值`(不需要引号)
  ```cmd
  set FINNHUB_API_KEY=xxx
  python main.py --mode daily
  ```
- **PowerShell**, 提示符长得像 `PS C:\Users\你的名字>`: 用 `$env:变量名="值"`
  ```powershell
  $env:FINNHUB_API_KEY="xxx"
  python main.py --mode daily
  ```

本地跑不受"夏令时时间判断"限制(那个判断只在GitHub Actions的定时触发时生效), 随时能跑。

## Discord `/stock` 查询指令 (可选功能, 单独部署)

在 `discord-bot/` 文件夹里, 是一套独立的东西(部署在Cloudflare Workers, 同样免费),
让你在Discord里输入 `/stock ticker:AAPL` 就能查某只股票最近一周的新闻。
详细部署步骤 + 踩坑记录见 `discord-bot/README.md`。

⚠️ 这个和上面的每日/每周简报是**两套独立的基础设施**(一个是GitHub Actions定时任务,
一个是Cloudflare Workers常驻服务), 因为斜杠指令需要"随时能被Discord调用"的能力,
定时任务做不到这件事。两边共用同一个 Finnhub API Key 就行。

**部署完之后同样不依赖你的电脑** —— 你的电脑只是当时用来"远程操作部署"这一步用的,
部署完成后Worker完全独立运行在Cloudflare, 密钥也存在Cloudflare账号里不在本地,
换电脑、关机都不影响它继续工作。只有当你以后想**修改代码**时才需要重新拉取仓库、
重新 `npm install` + `npm run deploy`, 密钥不需要重新设置。

## 当前版本的已知局限

- **FRED只给官方发布日期, 不含市场预期值**: 商业数据商(如Trading Economics)才有"预期值/前值",
  简报里的"意义解读"是AI基于数据本身的常识写的。
- **财报日历用白名单过滤噪音**: `main.py` 顶部的 `MAJOR_TICKERS` 维护了约80个大市值公司,
  可以随时增删。某周这些公司都没财报时会自动退回显示全量列表, 避免空白。
- **新闻没有精细筛选**: 抓的是Finnhub general分类的通用财经新闻, 质量依赖Gemini整理时的判断。
- **邮件HTML用的是内联样式的简化版设计**, 主流邮箱(Gmail/Apple Mail)显示没问题,
  个别老旧邮件客户端(比如Outlook桌面版)可能样式还原度打折扣。
- **没有联储官员讲话日程**: 目前没有免费API能稳定覆盖。

这些都不影响先跑起来看效果, 跑几天觉得哪块不准/不够用, 随时可以再调整。
