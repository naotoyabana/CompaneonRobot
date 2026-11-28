"""VLM（画像を読めるモデル）に写真を説明させる。

VLM は GX10 の vlm-server（Qwen3-VL-30B-A3B、ポート 30002、M5-1）。
llama-server は OpenAI と同じ形の API（/v1/chat/completions）で受け付ける。
画像は「data URL」（data:image/jpeg;base64,…）という、文字にした画像として文章と一緒に送る。
"""

import asyncio
import base64
import json
import time
import urllib.request

VLM_URL = "http://127.0.0.1:30002/v1/chat/completions"

# VLM への指示。説明の質はここで変わる（M5-3 で試しながら直す）
# （「ロボットのカメラの写真です」と前置きすると、それをくり返したり「カメラが写っている」と答えたりした）
PROMPT = (
    "写っている物と、それがどこにあるか（手前・奥・左・右）を、日本語で1〜2文で短く説明して。"
    "ぼやけていて分からない物は、分からないと書いて。前置きはいらない。"
)


def build_request(jpeg: bytes) -> dict:
    """VLM に送る中身（辞書）を作る。"""
    # TODO 10：jpeg（バイト列）を base64 の文字列にして、data URL を作る。
    #   ヒント：base64.b64encode(jpeg) はバイト列を返すので、.decode() で文字列にする。
    #           data URL は "data:image/jpeg;base64," + その文字列
    url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode() # ← ここを書く
    return {
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": url}},
            {"type": "text", "text": PROMPT},
        ]}],
        "max_tokens": 150,   # 説明が長くなりすぎないように
        "temperature": 0.2,  # 低いほど毎回同じような書き方になる
    }


def describe_sync(jpeg: bytes) -> str:
    """写真 1 枚を VLM に送り、説明文を返す（終わるまで待つ）。"""
    body = json.dumps(build_request(jpeg)).encode()
    request = urllib.request.Request(VLM_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        answer = json.load(response)
    # TODO 11：answer から説明文を取り出して返す。
    #   answer は {"choices": [{"message": {"role": "assistant", "content": "説明文"}}], ...} の形。
    #   ヒント：[0] でリストの最初、["キー"] で辞書の中身。最後に .strip() で前後の空白や改行を落とす。
    return answer["choices"][0]["message"]["content"].strip()


async def describe(jpeg: bytes) -> tuple[str, float]:
    """describe_sync を別の係（スレッド）で動かす。待っている間も体の電話（ping など）は止まらない。
    返すのは (説明文, かかった秒数)。"""
    start = time.monotonic()
    text = await asyncio.to_thread(describe_sync, jpeg)
    return text, time.monotonic() - start
