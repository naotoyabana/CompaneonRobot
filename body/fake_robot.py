# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets>=13"]
# ///
"""にせスタックチャン。ファームを触る前に、server.py が正しく動くかを試すためのもの。

本物と同じように体サーバーに電話をかけ、届いたデータを表示する。生存確認（ping）には返事（pong）をする。
使い方（server.py を起動したまま、別のターミナルで）：
    cd ~/companeonrobot/body && uv run fake_robot.py
"""

import asyncio
import json

from websockets.asyncio.client import connect

URL = "ws://127.0.0.1:8100/stackChan/ws?deviceType=StackChan"
NAMES = {0x04: "首の動き", 0x05: "カメラ開始", 0x06: "カメラ停止", 0x10: "生存確認（ping）"}


async def main():
    async with connect(URL, additional_headers={"Authorization": "hi-stack-chan"}) as ws:
        await ws.send('{"type":"hello", "msg":"Hello from StackChan!"}')
        print("つながった（にせスタックチャン）")
        async for message in ws:
            kind = message[0]
            length = int.from_bytes(message[1:5], "big")
            payload = message[5:]
            print(f"届いた：{NAMES.get(kind, hex(kind))}、長さ {length}（実際 {len(payload)}）")
            if kind == 0x04:
                print("  中身：", json.loads(payload))
            if kind == 0x10:
                await ws.send(bytes([0x11]) + (0).to_bytes(4, "big"))  # pong


asyncio.run(main())
