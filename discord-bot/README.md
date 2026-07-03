# Discord `/stock` 指令机器人 · 部署说明

这部分是独立的一套东西, 跟每日/每周简报的自动化脚本是分开部署的。
用的是 Cloudflare Workers(免费, 不需要信用卡, 每天10万次请求额度, 对个人使用完全用不完)。

**部署完之后不依赖你的电脑** —— Worker跑在Cloudflare的服务器上, 密钥也存在Cloudflare账号里,
你电脑关机、换电脑都不影响它继续工作。只有以后想改代码时才需要重新连电脑操作一次部署。

## 现在的效果

打 `/stock ticker:AAPL`, 会返回该股票最近一周的新闻, 每条包含:
- 中文翻译的标题(加粗)
- 一句话说明为什么重要(AI用中文总结)
- 原文链接 + 发布日期 + 新闻来源

标题翻译和一句话总结是Gemini生成的, **链接和日期是直接从Finnhub原始数据拼的, 不经过AI**——
这样能保证链接不会被AI写错或写丢。如果没配置Gemini Key, 会自动降级成显示原始英文标题+摘要,
不会报错。

## 第一步: 在Discord创建Application

1. 打开 https://discord.com/developers/applications
2. 点 "New Application", 起个名字
3. "General Information" 页面记下: **Application ID**(一串数字)、
   **Public Key**(一串很长的十六进制字符串)
4. "Bot" 页面点 "Reset Token" 拿到 **Bot Token**(只显示一次, 记得保存)

## 第二步: 把应用邀请进服务器

"OAuth2" → "URL Generator" → Scopes勾选 `applications.commands` → 复制链接浏览器打开授权

## 第三步: 部署Worker

需要先装 Node.js(https://nodejs.org 装LTS版本)

```bash
cd discord-bot
npm install
npx wrangler login          # 登录Cloudflare账号(免费注册, 不需要信用卡)

# 设置四个密钥(每条命令回车后会单独提示输入, 粘贴完直接回车)
npx wrangler secret put DISCORD_PUBLIC_KEY
npx wrangler secret put DISCORD_APP_ID
npx wrangler secret put FINNHUB_API_KEY
npx wrangler secret put GEMINI_API_KEY

npm run deploy
```

`DISCORD_APP_ID` 就是第一步的Application ID。`GEMINI_API_KEY` 可以跟每日简报脚本用**同一个**,
不用重新申请, 去 https://aistudio.google.com/apikey 复制。

部署成功后终端会打印一个网址, 类似 `https://market-brief-bot.你的子域名.workers.dev`,
**复制下来**, 下一步要用。

## 第四步: 把Worker网址告诉Discord

Developer Portal → 你的Application → "General Information" → "Interactions Endpoint URL"
粘贴上一步的网址 → 保存。保存瞬间Discord会发验证请求, 部署对了会自动通过。

## 第五步: 注册 `/stock` 指令(只需要做一次)

```bash
cd discord-bot
# Windows CMD:
set DISCORD_APP_ID=你的Application ID
set DISCORD_BOT_TOKEN=你的Bot Token
# Windows PowerShell:
# $env:DISCORD_APP_ID="你的Application ID"
# $env:DISCORD_BOT_TOKEN="你的Bot Token"
# Mac/Linux:
# export DISCORD_APP_ID="你的Application ID"
# export DISCORD_BOT_TOKEN="你的Bot Token"

python register_command.py
```

看到 "✅ 指令注册成功" 就完事了, 指令全局生效, 不需要每次部署都重新注册。

## 第六步: 测试

Discord频道输入 `/stock`, 自动弹出参数提示, 填 `ticker` 为 `AAPL` 之类的代码, 回车。
会先短暂显示"正在输入"状态(1-3秒, 因为要抓新闻+调AI翻译, 正常现象不是卡住了),
然后弹出中文新闻卡片。

---

## 踩坑记录 (实测遇到过的问题)

### `wrangler secret put` 要输入的是什么？
```bash
npx wrangler secret put DISCORD_PUBLIC_KEY
```
这行命令本身不带密钥值, `DISCORD_PUBLIC_KEY` 只是密钥的"名字"照抄就行, 回车后才会提示
`? Enter a secret value: »`, 这时候才粘贴真正的密钥内容。不要把密钥值直接写在命令里
(比如误把Application ID当成命令参数打进去了这种情况)。

### 提示 "There doesn't seem to be a Worker called xxx..."
第一次设置密钥时Cloudflare那边还没有这个Worker, 会问要不要先建一个空的存密钥, **选 Y**,
之后 `npm run deploy` 会把真正代码传上去替换掉。

### 提示 "You need to register a workers.dev subdomain"
给Worker申请免费公开网址, 必须要有, **选 Y**。子域名是Cloudflare账号全局前缀, 随便起一个
别人没用过的名字(比如 `你的名字-marketbrief`), 全局唯一, 小写字母/数字/连字符。

### 部署显示成功但浏览器打不开网址
大概率DNS还没生效(日志会提示"几分钟内更新"), 先等5分钟。或者用 `curl` 排除浏览器缓存/网络问题:
```bash
curl https://market-brief-bot.你的子域名.workers.dev
```
能返回 `Market Brief Discord Bot is running.` 说明Worker是通的, 只是浏览器那边有问题,
或者当前网络屏蔽了 `*.workers.dev`(不少见, 换个网络环境试试)。

### Discord报错 "The specified interactions endpoint url could not be verified"
排查顺序:
1. 先确认Worker本身是活的(见上一条)
2. 用实时日志抓真正报错:
   ```bash
   npx wrangler tail
   ```
   保持这个终端开着, 回Discord Portal再点一次保存Interactions Endpoint URL(内容不变也要重新点),
   切回终端看实时报错
3. 重新确认 `DISCORD_PUBLIC_KEY` 没有多余空格/换行, 重新 `npx wrangler secret put` 一遍

### 内容输出到一半就断了
Gemini的 `maxOutputTokens` 参数设太小导致的截断, 现在的代码已经调大过(2000), 如果你是更早
拉取的代码, 更新一下 `worker.js` 重新 `npm run deploy`。

### Windows下环境变量 `export` 报错
`export` 是Mac/Linux语法, Windows要看终端类型:
- **CMD**(提示符像 `C:\Users\你的名字>`): `set 变量名=值`
- **PowerShell**(提示符像 `PS C:\Users\你的名字>`): `$env:变量名="值"`

## 换电脑之后怎么办

不需要重新部署。Worker和所有密钥都在Cloudflare账号里, 跟你电脑无关。只有以后想**改代码**时,
才需要在新电脑上:
```bash
git clone <仓库地址>
cd market-brief/discord-bot
npm install
npx wrangler login    # 登录同一个Cloudflare账号
npm run deploy
```
密钥不需要重新设置。

## 常见问题

- **改指令名字/加新指令**: 改 `register_command.py` 里的 `command` 字典, 重新跑一次
- **想加更多指令**(比如查财报/查股价): 在 `worker.js` 的 `commandName === "stock"` 判断旁边
  加新分支, 同时在 `register_command.py` 里也注册新指令
- **免费额度够不够用**: Cloudflare每天10万次请求、Gemini每天几百到上千次, 个人用完全用不完
