# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets>=13"]
# ///
"""文字で話すにせスタックチャン。声を出さずに、会話（音声サーバー → LLM）を試すためのもの。

本物と同じように音声サーバー（:8000）に電話をかけ、本物と同じ道具の一覧を渡す。
打った文字は「聞き取った言葉」として送られ、音声認識を飛ばして LLM に届く。
返事は文字で表示する（音声も届くが捨てる）。道具を呼ばれたら表示して「成功」と返す（首は動かない）。

道具の一覧は、音声サーバーのログにある本物の返事（最新のもの）を使い、robot_tools.json にも保存する。
ログにないとき（コンテナを作り直した直後など）は robot_tools.json を使う。

使い方（GX10 で。本物のスタックチャンがつながっていてもよい）：
    cd ~/companeonrobot/chat && uv run text_chat.py
    「あなた：」に続けて打って Enter。q で終わる。
"""

import asyncio
import json
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

URL = "ws://127.0.0.1:8000/xiaozhi/v1/"
HEADERS = {
    "device-id": "fa:ke:ch:at:00:01",  # 本物と別の番号にする（本物の会話とまざらない）
    "client-id": str(uuid.uuid4()),
    "Protocol-Version": "1",
    "Authorization": "Bearer fake",
}
# 本物が最初に送るあいさつと同じもの（音声サーバーのログ「收到hello消息」から）
HELLO = {
    "type": "hello", "version": 1, "features": {"mcp": True}, "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
}
TOOLS_FILE = Path(__file__).with_name("robot_tools.json")
LOG_MARK = "收到mcp消息："  # 音声サーバーのログで、スタックチャンから届いた道具のやりとりの印


def load_tools() -> list:
    """本物のスタックチャンが返した道具の一覧を読む。"""
    logs = subprocess.run(["docker", "logs", "stackchan-server"], capture_output=True, text=True)
    lines = [line for line in (logs.stdout + logs.stderr).splitlines()
             if LOG_MARK in line and '"tools":[' in line]
    if lines:
        tools = json.loads(lines[-1].split(LOG_MARK, 1)[1])["payload"]["result"]["tools"]
        TOOLS_FILE.write_text(json.dumps(tools, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"道具の一覧：音声サーバーのログから {len(tools)} 個（{TOOLS_FILE.name} にも保存）")
        return tools
    tools = json.loads(TOOLS_FILE.read_text(encoding="utf-8"))
    print(f"道具の一覧：ログになかったので {TOOLS_FILE.name} から {len(tools)} 個")
    return tools


def detect_message(text: str) -> str:
    """打った文字を「聞き取った言葉」として送るメッセージ（JSON の文字列）を作る。"""
    # TODO 1：次の形の辞書を json.dumps(...) で文字列にして返す。
    #   {"type": "listen", "state": "detect", "text": 打った文字}
    #   ヒント：日本語をそのまま送るには json.dumps(辞書, ensure_ascii=False)
    return json.dumps({"type": "listen", "state": "detect", "text": text}, ensure_ascii=False)


def mcp_reply(request: dict, tools: list) -> dict | None:
    """音声サーバーからの道具の質問（MCP）に、本物のふりをして答える。返す辞書は payload の中身。"""
    method = request.get("method")
    msg_id = request.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-text-chat", "version": "1"}}}
    if method == "tools/list":
        # TODO 2：「何ができる？」への返事。上の initialize と同じ形で、result の中身を
        #   {"tools": tools} にした辞書を返す。
        #   （本物はこれで 14 個の道具の説明を渡している。説明が 1 文字でも違うと、LLM に届く文章が本物と変わる）
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}}
    if method == "tools/call":
        params = request.get("params", {})
        # TODO 3：呼ばれた道具の名前（params["name"]）と中身（params.get("arguments", {})）を
        #   「  道具：self.robot.set_head_angles {'yaw': 60, ...}」のように 1 行で表示し、
        #   成功の返事を返す。返事の result は本物と同じ形：
        #   {"content": [{"type": "text", "text": "true"}], "isError": False}
        #   （何も返さないと、音声サーバーは返事を待ったまま止まってしまう）
        print(f"道具：{params["name"]} {params.get("arguments", {})}")
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": "true"}], "isError": False}}
    return None  # それ以外（届いたお知らせなど）は返事しない


async def receive(ws, tools: list, session: dict, tools_sent: asyncio.Event, turn_done: asyncio.Event):
    """音声サーバーから届くものを受け取り続ける係。"""
    async for message in ws:
        if isinstance(message, bytes):
            continue  # 返事の音声（opus）。使わない
        data = json.loads(message)
        kind = data.get("type")
        if kind == "hello":
            session["id"] = data.get("session_id")
        elif kind == "mcp":
            reply = mcp_reply(data.get("payload", {}), tools)
            if reply is not None:
                await ws.send(json.dumps({"session_id": session["id"], "type": "mcp", "payload": reply},
                                         ensure_ascii=False))
                if data["payload"].get("method") == "tools/list":
                    tools_sent.set()
        elif kind == "tts":
            # TODO 4：返事の文字は {"type": "tts", "state": "sentence_start", "text": "..."} で 1 文ずつ届く。
            #   state が "sentence_start" なら「スタックチャン：…」と表示する。
            #   state が "stop" なら返事が終わったので turn_done.set() で入力の係に知らせる。
            #   ヒント：data.get("state")、data.get("text")
            state = data.get("state")
            if state == "sentence_start":
                print(f"スタックチャン：{data.get("text")}")
            elif state == "stop":
                turn_done.set()


async def open_call(tools: list):
    """音声サーバーに電話をかけ、道具の一覧を渡し終わるまで待つ。"""
    ws = await connect(URL, additional_headers=HEADERS)
    session = {"id": None}
    tools_sent, turn_done = asyncio.Event(), asyncio.Event()
    receiver = asyncio.create_task(receive(ws, tools, session, tools_sent, turn_done))
    await ws.send(json.dumps(HELLO))
    # 音声サーバーは hello の後に initialize、約 1 秒後に tools/list を聞いてくる
    await asyncio.wait_for(tools_sent.wait(), timeout=10)
    await asyncio.sleep(0.5)  # 受け取った一覧をサーバーが登録し終わるのを待つ
    print(f"{datetime.now():%H:%M:%S} つながった")
    return ws, receiver, turn_done


async def main():
    tools = load_tools()
    ws = receiver = turn_done = None
    while True:
        text = (await asyncio.to_thread(input, "あなた：")).strip()
        if text == "q":
            break
        if not text:
            continue
        if ws is None or receiver.done():
            # 30 秒話さないと音声サーバーが電話を切る（.config.yaml の close_connection_no_voice_time）
            ws, receiver, turn_done = await open_call(tools)
        turn_done.clear()
        try:
            await ws.send(detect_message(text))
            await asyncio.wait_for(turn_done.wait(), timeout=60)
        except (ConnectionClosed, asyncio.TimeoutError):
            print("（返事の途中で切れた／60 秒待っても終わらなかった）")
            ws = None
    if ws is not None:
        await ws.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        pass
