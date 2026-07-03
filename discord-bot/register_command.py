"""
一次性脚本: 向Discord注册 /stock 这个斜杠指令。
只需要成功运行一次(除非以后想改指令的名字/参数), 不需要放进定时任务里。

用法:
    export DISCORD_APP_ID="你的Application ID"
    export DISCORD_BOT_TOKEN="你的Bot Token"
    python register_command.py
"""

import os
import requests

APP_ID = os.environ["DISCORD_APP_ID"]
BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]

url = f"https://discord.com/api/v10/applications/{APP_ID}/commands"
headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}

command = {
    "name": "stock",
    "description": "查询某只股票最近一周的新闻",
    "options": [
        {
            "name": "ticker",
            "description": "股票代码, 例如 AAPL",
            "type": 3,  # STRING
            "required": True,
        }
    ],
}

resp = requests.post(url, headers=headers, json=command, timeout=15)
print(resp.status_code, resp.text)
if resp.status_code in (200, 201):
    print("\n✅ 指令注册成功, 去Discord频道试试输入 /stock")
else:
    print("\n❌ 注册失败, 检查一下 APP_ID 和 BOT_TOKEN 是否正确")
