# Discord `/stock` 指令机器人 · 部署说明

这部分是独立的一套东西, 跟每日/每周简报的自动化脚本是分开部署的。
用的是 Cloudflare Workers(免费, 不需要信用卡, 每天10万次请求额度, 对个人使用完全用不完)。

**部署完之后不依赖你的电脑** —— Worker跑在Cloudflare的服务器上, 密钥也存在Cloudflare账号里,
你电脑关机、换电脑都不影响它继续工作。只有以后想改代码时才需要重新连电脑操作一次部署。

## 第一步: 在Discord创建Application

1. 打开 https://discord.com/developers/applications
2. 点 "New Application", 起个名字(比如 "MarketBrief Bot")
3. 进去之后左侧菜单点 "General Information", 记下两个东西:
   - **Application ID**(一串数字)
   - **Public Key**(一串很长的十六进制字符串, 字母数字混合, 跟Application ID长得不一样)
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

# 设置两个密钥(会提示你输入, 粘贴完直接回车)
npx wrangler secret put DISCORD_PUBLIC_KEY
npx wrangler secret put FINNHUB_API_KEY

# 部署
npm run deploy
```

部署成功后, 终端会打印出一个网址, 类似:
`https://market-brief-bot.你的子域名.workers.dev`

**这个网址复制下来**, 下一步要用。

## 第四步: 把Worker网址告诉Discord

1. 回到 Discord Developer Portal → 你的Application → "General Information"
2. 找到 "Interactions Endpoint URL" 这一栏, 粘贴上一步的Worker网址, 保存
3. 保存的瞬间Discord会向这个网址发一个验证请求, 如果Worker部署对了会自动验证通过

## 第五步: 注册 `/stock` 指令(只需要做一次)

```bash
cd discord-bot
python register_command.py
```

需要先设置两个环境变量(见下方"Windows用户注意"), 再跑上面这行。看到
"✅ 指令注册成功" 就完事了。指令是全局生效的, 不需要每次部署都重新注册,
除非以后想改指令名字或参数。

## 第六步: 测试

去你的Discord服务器, 随便一个频道输入 `/stock`, 应该会自动弹出参数提示,
填 `ticker` 为 `AAPL` 之类的股票代码, 回车, 几秒内应该会收到一张新闻卡片。

---

## 部署过程中的踩坑记录 (实测遇到过的问题)

### `wrangler secret put` 那一步, 提示要输入的是什么？

```bash
npx wrangler secret put DISCORD_PUBLIC_KEY
```
这一行命令本身**不需要**你带着密钥值一起打, `DISCORD_PUBLIC_KEY` 只是密钥的"名字"(固定写死,
照抄就行), 回车之后它才会单独提示 `? Enter a secret value: »`, 这时候才轮到你粘贴真正的
Public Key(去Discord Developer Portal → General Information页面复制)。

同理设置第二个密钥:
```bash
npx wrangler secret put FINNHUB_API_KEY
```
提示的时候粘贴你的Finnhub API Key。

### 提示 "There doesn't seem to be a Worker called xxx. Do you want to create a new Worker..."

第一次设置密钥时, Cloudflare那边还没有这个Worker(还没正式部署过), 所以wrangler会问你要不要
先建一个空的来存密钥。**选 Y**, 之后 `npm run deploy` 会把真正的代码传上去替换掉这个空壳。

### 提示 "You need to register a workers.dev subdomain"

这是给你的Worker申请一个免费公开网址, 必须要有, **选 Y**。子域名(subdomain)是你Cloudflare
账号全局的前缀(以后所有Worker都会挂在这个前缀下), 只能小写字母/数字/连字符, 而且要全球唯一,
随便起一个别人没用过的名字就行, 比如 `你的名字-marketbrief` 或者加几个数字保证不重名。

最终Worker网址会是: `https://market-brief-bot.你起的这个名字.workers.dev`

### 部署显示成功, 但浏览器打不开这个网址

大概率是**DNS还没生效** —— 部署日志最后会有一句 "It may take a few minutes for DNS records
to update", 首次注册 workers.dev 子域名, DNS传播一般需要几分钟, 有时候到10分钟左右。

排查顺序:
1. 先等5分钟左右重新打开试试
2. 用 `curl` 代替浏览器测试, 排除浏览器缓存/网络问题:
   ```bash
   curl https://market-brief-bot.你的子域名.workers.dev
   ```
   如果这条命令能返回 `Market Brief Discord Bot is running.` 说明Worker其实是通的,
   只是浏览器那边有缓存, 或者你当前网络环境屏蔽了 `*.workers.dev` 域名(不少见)
3. 如果 `curl` 也不通, 去 Cloudflare 后台 `dashboard → Workers → 你的Worker` 确认部署状态

### Discord报错 "The specified interactions endpoint url could not be verified"

这是最常遇到的报错, 排查顺序:

1. **先确认Worker本身是活的**: 浏览器/curl打开Worker网址, 应该显示
   `Market Brief Discord Bot is running.`
2. **用实时日志抓真正的报错**(最快定位问题的办法):
   ```bash
   npx wrangler tail
   ```
   这个命令会一直挂着监听, 不会自动结束, 属于正常现象。**保持这个终端开着**,
   然后回Discord Portal再点一次保存Interactions Endpoint URL(内容不变也要重新点保存,
   这样会触发一次新的验证请求), 切回终端就能看到实时报错内容
3. **重新确认Public Key**: 复制粘贴时最容易带上多余的空格/换行, 可以重新设置一遍:
   ```bash
   npx wrangler secret put DISCORD_PUBLIC_KEY
   ```
   去Discord Portal重新复制一遍, 确保是完整的十六进制字符串, 前后没有空格
4. **代码层面的一个已知修复**: 早期版本的 `worker.js` 把请求体当"文本字符串"传给验证函数,
   但Discord官方教程的写法是当"原始字节(ArrayBuffer)"传, 两者在某些场景下编码方式不完全一致,
   可能导致验证失败。现在这版代码已经改成官方推荐写法(`request.clone().arrayBuffer()`),
   如果你是更早期拉取的代码, 更新一下 `worker.js` 再重新 `npm run deploy`

### Windows下环境变量怎么设置(`export` 命令不认识)

`export` 是Mac/Linux(bash)的语法, Windows不通用, 会报错
`'export' is not recognized as an internal or external command`。看你的终端类型换成对应语法:

- **CMD(命令提示符)**, 提示符长得像 `C:\Users\你的名字>`:
  ```cmd
  set DISCORD_APP_ID=1522682100690583722
  set DISCORD_BOT_TOKEN=你的BotToken
  python register_command.py
  ```
  (不需要引号, 等号前后不要留空格)

- **PowerShell**, 提示符长得像 `PS C:\Users\你的名字>`:
  ```powershell
  $env:DISCORD_APP_ID="1522682100690583722"
  $env:DISCORD_BOT_TOKEN="你的BotToken"
  python register_command.py
  ```

## 常见问题

- **改指令名字/加新指令**: 改 `register_command.py` 里的 `command` 字典, 重新跑一次这个脚本
- **想加更多指令**(比如查财报/查股价): 在 `worker.js` 的 `if (commandName === "stock")` 那块
  旁边加新的 `else if (commandName === "xxx")` 分支, 同时在 `register_command.py` 里也注册新指令
- **免费额度会不会不够用**: Cloudflare Workers免费层每天10万次请求, 个人用完全用不完
- **换电脑要重新弄吗**: 不需要。Worker和密钥都在Cloudflare账号里, 跟你电脑无关。
  只有以后想**改代码**时, 才需要在新电脑上 `git clone` → `npm install` → `npx wrangler login`
  (登录同一个Cloudflare账号) → `npm run deploy`, 密钥不用重新设置
