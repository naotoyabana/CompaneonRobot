# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets>=13"]
# ///
"""体サーバー（最小版）。スタックチャンの「体の電話」（WS-Avatar）を受ける。

起動：  cd ~/companeonrobot/body && uv run server.py
使い方：起動したら、ターミナルに「yaw pitch」（度）を打つと首が動く。例：30 10
        3 つ目に速さ（0〜1000、省略すると 300）も書ける。例：30 45 700
        角度は「今の向きからのずれ」ではなく決まった向き：
          yaw（横）  0 が正面、プラスが右、-128〜128
          pitch（縦）0 がまっすぐ前、90 が真上、実際に動けるのは 3〜87
        q で終了。

ファーム側の決まり（firmware/main/hal/hal_ws_avatar.cpp）：
- 接続先：ws://<GX10>:8100/stackChan/ws?deviceType=StackChan
- 1 つのデータ（バイナリ）：[種類 1 バイト][長さ 4 バイト、大きい桁が先][中身]
- 首の角度は 0.1 度単位（30 度 → 300）。速さは 0〜1000
"""

import asyncio
import json

from websockets.asyncio.server import serve

PORT = 8100

# データの種類（hal_ws_avatar.cpp の DataType と同じ番号）
JPEG = 0x02
CONTROL_AVATAR = 0x03
CONTROL_MOTION = 0x04
START_CAMERA = 0x05
STOP_CAMERA = 0x06
TEXT_MESSAGE = 0x07
HEARTBEAT_PING = 0x10
HEARTBEAT_PONG = 0x11


def make_packet(kind: int, payload: bytes = b"") -> bytes:
    """送るデータを作る：[種類 1 バイト][長さ 4 バイト][中身]"""
    # TODO 1：3 つをつなげて返す。
    #   ヒント：bytes([kind]) で 1 バイト。
    #           len(payload).to_bytes(4, "big") で長さを 4 バイト（大きい桁が先）に。
    #           bytes どうしは + でつなげられる。
    return bytes([kind])+len(payload).to_bytes(4, "big")+payload


def parse_packet(data: bytes) -> tuple[int, bytes]:
    """届いたデータを (種類, 中身) に分ける。"""
    # TODO 2：data[0] が種類。中身は 5 バイト目から（data[5:]）。
    #   （長さの 4 バイト data[1:5] は、今回は使わなくてよい）
    return (data[0], data[5:])


def motion_json(yaw_deg: int, pitch_deg: int, speed: int = 300) -> str:
    """首を動かす指示（JSON の文字列）を作る。"""
    # TODO 3：次の形の辞書を作り、json.dumps(...) で文字列にして返す。
    #   {"yawServo": {"angle": 横の角度×10, "speed": speed},
    #    "pitchServo": {"angle": 縦の角度×10, "speed": speed}}
    #   横：プラスがスタックチャンから見て右（最大 ±128 度）。縦：プラスが上（最大 90 度）
    return json.dumps({"yawServo": {"angle": yaw_deg*10, "speed": speed}, "pitchServo": {"angle": pitch_deg*10, "speed": speed}})


# 今つながっているスタックチャン（1 台だけ想定）
robot = None


async def heartbeat(ws):
    """5 秒ごとに生存確認（ping）を送る。"""
    while True:
        # TODO 4：HEARTBEAT_PING を（中身なしで）送る。
        #   ヒント：await ws.send(make_packet(...))
        await ws.send(make_packet(HEARTBEAT_PING))
        await asyncio.sleep(5)


async def handle_robot(ws):
    """スタックチャンが電話をかけてきたら、ここが動く。"""
    global robot
    print(f"つながった：{ws.remote_address[0]}  {ws.request.path}")
    print(f"  合言葉：{ws.request.headers.get('Authorization')}")
    robot = ws
    beat = asyncio.create_task(heartbeat(ws))
    try:
        async for message in ws:  # 届くたびに 1 回まわる
            if isinstance(message, str):  # 文字（最初の hello など）
                print(f"文字：{message}")
                continue
            kind, payload = parse_packet(message)
            if kind == HEARTBEAT_PONG:
                pass  # 生存確認の返事。うるさいので表示しない
            else:
                print(f"届いた：種類 0x{kind:02x}、{len(payload)} バイト")
    finally:
        beat.cancel()
        robot = None
        print("切れた")


async def command_loop():
    """ターミナルに打った「yaw pitch」を首の指示にして送る。"""
    while True:
        line = await asyncio.to_thread(input, "yaw pitch [速さ]> ")
        if line.strip() == "q":
            return
        if robot is None:
            print("  まだスタックチャンがつながっていない")
            continue
        try:
            numbers = [int(x) for x in line.split()]
            yaw, pitch = numbers[0], numbers[1]
            speed = numbers[2] if len(numbers) >= 3 else 300
        except (ValueError, IndexError):
            print("  例：30 10　または　30 45 700")
            continue
        await robot.send(make_packet(CONTROL_MOTION, motion_json(yaw, pitch, speed).encode()))
        print(f"  送った：yaw {yaw} 度、pitch {pitch} 度、速さ {speed}")


async def main():
    async with serve(handle_robot, "0.0.0.0", PORT):
        print(f"体サーバー起動：ポート {PORT}")
        await command_loop()


if __name__ == "__main__":
    asyncio.run(main())
