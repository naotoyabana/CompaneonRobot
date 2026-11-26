# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets>=13", "pillow"]
# ///
"""にせスタックチャン。ファームを触る前に、server.py が正しく動くかを試すためのもの。

本物と同じように体サーバーに電話をかけ、届いたデータを表示する。生存確認（ping）には返事（pong）をする。
カメラ開始（0x05）が届くと、本物と同じく 0.35 秒ごとに JPEG（0x02）を送る。カメラ停止（0x06）で止める。
画像は 320×240 で、何枚目かの番号を書いたもの（本物のカメラではない）。
使い方（server.py を起動したまま、別のターミナルで）：
    cd ~/companeonrobot/body && uv run fake_robot.py
"""

import asyncio
import io
import json

from PIL import Image, ImageDraw
from websockets.asyncio.client import connect

URL = "ws://127.0.0.1:8100/stackChan/ws?deviceType=StackChan"
NAMES = {0x04: "首の動き", 0x05: "カメラ開始", 0x06: "カメラ停止", 0x10: "生存確認（ping）"}


def packet(kind: int, payload: bytes = b"") -> bytes:
    return bytes([kind]) + len(payload).to_bytes(4, "big") + payload


def fake_jpeg(number: int) -> bytes:
    """番号を書いた 320×240 の JPEG を作る。"""
    image = Image.new("RGB", (320, 240), (40, 80, 160))
    ImageDraw.Draw(image).text((20, 100), f"fake frame {number}", fill=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=20)  # 本物と同じ画質 20
    return buffer.getvalue()


async def camera(ws):
    """撮影中：0.35 秒ごとに JPEG を送る。"""
    number = 0
    while True:
        number += 1
        await ws.send(packet(0x02, fake_jpeg(number)))
        await asyncio.sleep(0.35)


async def main():
    async with connect(URL, additional_headers={"Authorization": "hi-stack-chan"}) as ws:
        await ws.send('{"type":"hello", "msg":"Hello from StackChan!"}')
        print("つながった（にせスタックチャン）")
        streaming = None  # 撮影中なら、その係（タスク）
        async for message in ws:
            kind = message[0]
            length = int.from_bytes(message[1:5], "big")
            payload = message[5:]
            if kind != 0x10:
                print(f"届いた：{NAMES.get(kind, hex(kind))}、長さ {length}（実際 {len(payload)}）")
            if kind == 0x04:
                print("  中身：", json.loads(payload))
            elif kind == 0x05 and streaming is None:
                streaming = asyncio.create_task(camera(ws))
                await ws.send("camera stream started")  # 本物も文字で返事をする
            elif kind == 0x06 and streaming is not None:
                streaming.cancel()
                streaming = None
                await ws.send("camera stream stopped")
            elif kind == 0x10:
                await ws.send(packet(0x11))  # pong


asyncio.run(main())
