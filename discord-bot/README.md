# Discord `/stock` 指令机器人 · 部署说明

这部分是独立的一套东西, 跟每日/每周简报的自动化脚本是分开部署的。
用的是 Cloudflare Workers(免费, 不需要信用卡, 每天10万次请求额度, 对个人使用完全用不完)。

## 第一步: 在Discord创建Application

1. 打开 https://discord.com/developers/applications
2. 点 "New Application", 起个名字(比如 "MarketBrief Bot")
3. 进去之后左侧菜单点 "General Information", 记下两个东西:
   - **Application ID**
   - **Public Key**
4. 左侧菜单点 "Bot", 点 "Reset Token" 拿到 **Bot Token**(只显示一次, 记得复制保存)

## 第二步: 把这个"应用"邀请进你的服务器

1. 还是在Developer Portal, 左侧菜单点 "OAuth2" → "URL Generator"
2. Scopes 勾选 `applications.commands`(斜杠指令必选)
3. 复制生成的链接, 浏览器打开, 选择你的服务器, 授权

## 第三步: 部署Worker

需要先装 Node.js(如果还没装, 去 https://nodejs.org 装LTS版本)

```bash
cd discord-bot
npm install

# 登录Cloudflare账号(没有的话免费注册一个, 不需要信用卡)
npx wrangler login

# 设置两个密钥(会提示你输入, 输入完直接回车)
npx wrangler secret put DISCORD_PUBLIC_KEY
npx wrangler secret put FINNHUB_API_KEY

# 部署
npm run deploy
```

部署成功后, 终端会打印出一个网址, 类似:
`https://market-brief-bot.你的用户名.workers.dev`

**这个网址复制下来**, 下一步要用。

## 第四步: 把Worker网址告诉Discord

1. 回到 Discord Developer Portal → 你的Application → "General Information"
2. 找到 "Interactions Endpoint URL" 这一栏, 粘贴上一步的Worker网址, 保存
3. 保存的瞬间Discord会向这个网址发一个验证请求, 如果Worker部署对了会自动验证通过;
   如果报错, 大概率是 `DISCORD_PUBLIC_KEY` 设置错了, 回第三步检查

## 第五步: 注册 `/stock` 指令(只需要做一次)

```bash
cd discord-bot
export DISCORD_APP_ID="第一步拿到的Application ID"
export DISCORD_BOT_TOKEN="第一步拿到的Bot Token"
python register_command.py
```

看到 "✅ 指令注册成功" 就完事了。指令注册是全局生效的, 不需要每次部署都重新注册,
除非你以后想改指令名字或者参数。

## 第六步: 测试

去你的Discord服务器, 随便一个频道输入 `/stock`, 应该会自动弹出参数提示,
填 `ticker` 为 `AAPL` 之类的股票代码, 回车, 几秒内应该会收到一张新闻卡片。

## 常见问题

- **改指令名字/加新指令**: 改 `register_command.py` 里的 `command` 字典, 重新跑一次这个脚本
- **想加更多指令**(比如查财报/查股价): 在 `worker.js` 的 `if (commandName === "stock")` 那块
  旁边加新的 `else if (commandName === "xxx")` 分支, 同时在 `register_command.py` 里也注册新指令
- **免费额度会不会不够用**: Cloudflare Workers免费层每天10万次请求, 你一个人用完全用不完,
  不用担心
