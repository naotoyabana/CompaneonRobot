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
        cam on で撮影を始め（届いた画像は captures/ に保存）、cam off で止める。
        look yaw pitch で、その向きを見て VLM に説明させる（M5-3）。例：look 45 20
          首を向ける → 止まるのを待つ → その後に届いた 1 枚を captures/ に保存 → 説明を表示
          結果は observations.db（SQLite）にも保存する（M5-4）。log [件数] で新しい順に表示
        patrol on / patrol off で自動の見回し（M5-5）を始める／止める。
          ターミナルで起動したときは止まった状態で始まる。systemd のときは最初から見回す。
        q で終了。

ファーム側の決まり（firmware/main/hal/hal_ws_avatar.cpp）：
- 接続先：ws://<GX10>:8100/stackChan/ws?deviceType=StackChan
- 1 つのデータ（バイナリ）：[種類 1 バイト][長さ 4 バイト、大きい桁が先][中身]
- 首の角度は 0.1 度単位（30 度 → 300）。速さは 0〜1000
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosedError

import memory  # 同じフォルダの memory.py（見たものを SQLite に記録する）
import vision  # 同じフォルダの vision.py（VLM に写真を説明させる）

PORT = 8100
CAPTURE_DIR = Path(__file__).parent / "captures"  # 画像の保存先（body/captures/）

# データの種類（hal_ws_avatar.cpp の DataType と同じ番号）
JPEG = 0x02
CONTROL_AVATAR = 0x03
CONTROL_MOTION = 0x04
START_CAMERA = 0x05
STOP_CAMERA = 0x06
TEXT_MESSAGE = 0x07
HEARTBEAT_PING = 0x10
HEARTBEAT_PONG = 0x11

# look の決まり
LOOK_SPEED = 500        # 首の速さ（会話の LLM と同じ「ふつう」）
SETTLE_SECONDS = 1.5    # 首を向けてから止まるまで待つ秒数
FRAME_TIMEOUT = 10      # その後の 1 枚を待つ最大の秒数（撮影は 2 秒に 1 枚。会話中は止まる）

# 自動の見回し（M5-5）
PATROL_SECONDS = 30     # 1 方向ごとの間隔
# 回る向き (yaw, pitch)。下の段を左→右、上の段を右→左（端から端へ一気に振らない）
PATROL = [(-90, 10), (-45, 10), (0, 10), (45, 10), (90, 10),
          (90, 40), (45, 40), (0, 40), (-45, 40), (-90, 40)]


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


def save_jpeg(payload: bytes) -> Path:
    """届いた JPEG を captures/ にファイルとして保存し、保存先を返す。"""
    CAPTURE_DIR.mkdir(exist_ok=True)  # フォルダがなければ作る
    # TODO 5：時刻入りのファイル名を作り、payload をそのまま書き込んで、保存先を返す。
    #   ヒント：datetime.now().strftime("%Y%m%d-%H%M%S-%f") で「20261126-153012-345678」の形の文字列。
    #           [:-3] で最後の 3 文字を落とすと、ミリ秒まで（…-345）になる。
    #           path = CAPTURE_DIR / (名前 + ".jpg") で保存先。
    #           path.write_bytes(payload) でバイト列をそのままファイルに書く。
    name = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    path = CAPTURE_DIR / (name + ".jpg")
    path.write_bytes(payload)
    return path


# 今つながっているスタックチャン（1 台だけ想定）
robot = None
# 合図なしで切れた回数（起動してから）。M4 で「どのくらい切れるか」を見るため
drops = 0
# 撮影の状態
camera_on = False     # 撮影中か（cam on か look で始めた）
save_all = False      # 届いた画像を全部保存するか（cam on のときだけ。look は使った 1 枚だけ保存）
latest_frame = None   # 最後に届いた画像：(届いた時刻, JPEG のバイト列)。時刻は time.monotonic()
patrol_on = False     # 自動の見回しをしているか
# look を 1 度に 1 つだけ動かすための鍵（手で打った look と見回しの look が混ざらないように）
look_lock = asyncio.Lock()


async def heartbeat(ws):
    """5 秒ごとに生存確認（ping）を送る。"""
    while True:
        # TODO 4：HEARTBEAT_PING を（中身なしで）送る。
        #   ヒント：await ws.send(make_packet(...))
        await ws.send(make_packet(HEARTBEAT_PING))
        await asyncio.sleep(5)


async def handle_robot(ws):
    """スタックチャンが電話をかけてきたら、ここが動く。"""
    global robot, drops, camera_on, save_all, latest_frame
    print(f"つながった：{ws.remote_address[0]}  {ws.request.path}")
    print(f"  合言葉：{ws.request.headers.get('Authorization')}")
    robot = ws
    camera_on = save_all = False  # つなぎ直したスタックチャンは撮影していない
    beat = asyncio.create_task(heartbeat(ws))
    count = 0
    try:
        async for message in ws:  # 届くたびに 1 回まわる
            if isinstance(message, str):  # 文字（最初の hello など）
                print(f"文字：{message}")
                if message == "camera stream stopped":
                    print(f"  画像を {count} 枚保存した（captures/）")
                    count = 0
                continue
            kind, payload = parse_packet(message)
            if kind == HEARTBEAT_PONG:
                pass  # 生存確認の返事。うるさいので表示しない
            elif kind == JPEG:
                # TODO 12：届いた時刻と画像を latest_frame に覚えておく（look が使う）。
                #   ヒント：(time.monotonic(), payload) のように 2 つを ( ) で 1 組にできる。
                #           time.monotonic() は「時計を合わせても戻らない」秒数。差を測るのに使う。
                # ← ここを書く
                latest_frame = (time.monotonic(), payload)
                if save_all:
                    path = save_jpeg(payload)
                    count += 1
                    if count == 1:  # 1 枚目だけ表示
                        print(f"画像：{path.name}（{len(payload)} バイト）")
            else:
                print(f"届いた：種類 0x{kind:02x}、{len(payload)} バイト")
    except ConnectionClosedError:
        # ここに来るのは、スタックチャンが「切るね」の合図なしで切れたとき（今まで長い Traceback が出ていたもの）。
        # 受け止めると Traceback は出なくなる。スタックチャンは自分でつなぎ直してくる。
        # TODO 7：drops を 1 増やし、時刻と回数を 1 行で表示する。例：「15:20:01 合図なしで切れた（3 回目）」
        #   ヒント：datetime.now().strftime("%H:%M:%S") で「15:20:01」。
        #           drops は上で global と書いてあるので、ここで drops += 1 と書ける。
        drops += 1
        print(f"{datetime.now().strftime("%H:%M:%S")} 合図なしで切れた（{drops} 回目）")
    finally:
        beat.cancel()
        # TODO 9：スタックチャンは切れると 0.5 秒ほどで新しい電話をかけ直してくる。古い電話の「切れた」に
        #   サーバーが気づくのが、新しい電話の「つながった」より後になると、ここで新しい電話の robot まで
        #   None にしてしまい、首の指示が送れなくなる（2026-11-27 の 1 時間テストで起きた）。
        #   → robot が「この電話（ws）」のときだけ None にする。
        #   ヒント：「同じものか」は is で比べる（if robot is ws:）。
        if robot is ws:
            robot = None
            print("切れた")
        else:
            print("古い電話を片付けた（新しい電話はつながったまま）")


async def look(yaw: int, pitch: int):
    """その向きを見て、(保存先, 説明文, VLM の秒数) を返す。画像が来なければ None。
    鍵（look_lock）を持っている間だけ動く。ほかの look が動いていたら、終わるまで待つ。"""
    async with look_lock:
        return await look_unlocked(yaw, pitch)


async def look_unlocked(yaw: int, pitch: int):
    global camera_on
    if not camera_on:
        await robot.send(make_packet(START_CAMERA))
        camera_on = True
    await robot.send(make_packet(CONTROL_MOTION, motion_json(yaw, pitch, LOOK_SPEED).encode()))
    await asyncio.sleep(SETTLE_SECONDS)
    since = time.monotonic()  # これより後に届いた画像なら、首が止まってから撮ったもの
    # TODO 13：since より後に届いた画像を待つ。FRAME_TIMEOUT 秒たっても来なければ None を返す。
    #   ヒント：while 「まだ来ていない」: の形でくり返す。「まだ来ていない」は
    #           latest_frame is None or latest_frame[0] <= since
    #           くり返しの中では、時間切れ（time.monotonic() > since + FRAME_TIMEOUT）なら return None、
    #           そうでなければ await asyncio.sleep(0.1) で少し待つ。
    # ← ここを書く（while ...）
    while latest_frame is None or latest_frame[0] <= since:
        if time.monotonic() > since + FRAME_TIMEOUT:
            return None
        else:
            await asyncio.sleep(0.1)
    jpeg = latest_frame[1]
    path = save_jpeg(jpeg)
    text, seconds = await vision.describe(jpeg)
    memory.save(yaw, pitch, text, path.name, seconds)
    return path, text, seconds


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


async def patrol():
    """自動の見回し。PATROL_SECONDS ごとに、PATROL の向きを順に look する。"""
    i = 0  # 次に見る向きの番号（PATROL の何番目か）
    while True:
        await asyncio.sleep(PATROL_SECONDS)
        if not patrol_on or robot is None:
            continue
        # TODO 18：PATROL の i 番目の向きを取り出して look する。
        #   ・画像が来なかったら（None）、「会話中？」と 1 行表示して、i は進めない（同じ向きを次にやり直す）。
        #   ・説明が返ったら、時刻・向き・説明文を 1 行表示して、i を 1 進める。最後まで行ったら 0 に戻す。
        #   ・VLM が止まっているなどでエラーになっても見回し全体が止まらないように、look は try で囲み、
        #     except Exception as e: で受けて 1 行表示する（i は進めない）。
        #   ヒント：yaw, pitch = PATROL[i]
        #           「1 進めて、最後まで行ったら 0」は i = (i + 1) % len(PATROL)（% は割った余り）
        #           時刻は now()（上に用意した）
        try:
            yaw, pitch = PATROL[i]
            result = await look(yaw, pitch)
            if result is None:
                print("会話中？")
            else:
                path, text, seconds = result
                print(f"  見た：{path.name} (VLM {seconds:.1f} 秒)\n  説明文 {text}")
                i = (i + 1) % len(PATROL)
        except Exception as e:
            print(e)

async def command_loop():
    """ターミナルに打った指示（yaw pitch、cam on/off、look）を送る。"""
    global camera_on, save_all, patrol_on
    while True:
        line = await asyncio.to_thread(input, "yaw pitch [速さ] / cam on|off / look yaw pitch / log [件数] / patrol on|off> ")
        if line.strip() == "q":
            return
        # TODO 19：line.strip() が "patrol on" なら patrol_on を True に、"patrol off" なら False にして、
        #   「見回し：開始（30 秒ごと）」などと 1 行表示して continue。
        #   （patrol_on は上で global と書いてあるので、ここで書き換えられる）
        # ← ここを書く
        if line.strip() == "patrol on":
            patrol_on = True
            print("見回し：開始（30 秒ごと）")
            continue
        if line.strip() == "patrol off":
            patrol_on = False
            print("見回し：終了")
            continue
        if line.startswith("log"):  # 記録を見るだけなので、スタックチャンがいなくても使える
            words = line.split()
            limit = int(words[1]) if len(words) >= 2 and words[1].isdigit() else 10
            for id_, time_, yaw, pitch, description in memory.latest(limit):
                print(f"  {id_:4d} {time_} ({yaw:4d}, {pitch:3d}) {description}")
            continue
        if robot is None:
            print("  まだスタックチャンがつながっていない")
            continue
        # TODO 6：line.strip() が "cam on" なら START_CAMERA を、"cam off" なら STOP_CAMERA を
        #   （中身なしで）送り、「送った：撮影開始」などと表示して continue（下の yaw pitch の処理に進まない）。
        #   ヒント：送り方は下の robot.send(make_packet(...)) と同じ。中身なしは TODO 4 と同じ。
        if line.strip() == "cam on":
            await robot.send(make_packet(START_CAMERA))
            camera_on = save_all = True
            print("  送った：撮影開始")
            continue
        if line.strip() == "cam off":
            await robot.send(make_packet(STOP_CAMERA))
            camera_on = save_all = False
            print("  送った：撮影終了")
            continue
        if line.startswith("look"):
            # TODO 14：「look 45 20」の 45 と 20 を取り出して look(yaw, pitch) を呼び、結果を表示する。
            #   ヒント：line.split() で ["look", "45", "20"] になる。数字は int(...) で。
            #           書き間違い（数字でない、足りない）は、下の yaw pitch と同じく try/except で受けて例を表示。
            #           result = await look(yaw, pitch)。None なら「画像が来ない（会話中？）」と表示。
            #           そうでなければ path, text, seconds = result として、例えば
            #             「  見た：20261128-170000-123.jpg（VLM 0.6 秒）」と「  説明文」の 2 行を表示。
            try:
                yaw = int(line.split()[1])
                pitch = int(line.split()[2])
            except (ValueError, IndexError):
                print("  例：look 45 20")
                continue
            result = await look(yaw, pitch)
            if result is None:
                print("画像が来ない（会話中？）")
            else:
                path, text, seconds = result
                print(f"  見た：{path.name} (VLM {seconds:.1f} 秒)\n  説明文 {text}")
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
    global patrol_on
    async with serve(handle_robot, "0.0.0.0", PORT):
        print(f"体サーバー起動：ポート {PORT}")
        patrol_task = asyncio.create_task(patrol())  # 見回しの係。patrol_on が True のときだけ動く
        # TODO 8：ターミナルから起動したときだけ command_loop() で指示を受け付ける。
        #   systemd で動いているとき（ターミナルがない）は、指示は受け付けず、電話を受けるだけにする。
        #   ヒント：sys.stdin.isatty() は、キーボードを打てるターミナルなら True、systemd なら False。
        #           False のときは「ターミナルなし：電話を受けるだけ」のように 1 行表示してから
        #           await asyncio.Future() と書く（何も起きない約束を待つ＝止められるまでずっと待つ）。
        #           ここで main() が終わると、async with を抜けて電話の受け口も閉じてしまう。
        if(sys.stdin.isatty()):
            await command_loop()
        else:
            print(f"ターミナルなし：電話を受けて、見回す（{PATROL_SECONDS} 秒ごと）")
            patrol_on = True
            await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
