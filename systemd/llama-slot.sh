#!/bin/sh
# llama-server の「読み込み済みの指示文」（スロット 0 の KV キャッシュ）を保存・復元する。
#   save    : 止める直前に呼ぶ（systemd の ExecStop）
#   restore : 起動した直後に呼ぶ（systemd の ExecStartPost）
# 保存先は llama-server の --slot-save-path（/home/utaf3/llama-slots）。
URL=http://127.0.0.1:30000
FILE=slot0.bin
DIR=/home/utaf3/llama-slots

case "$1" in
  save)
    # いちばん長い指示文を持っているスロットを保存する（会話がスロット 0 以外に入ることもあるため）
    ID=$(curl -sf -m 5 "$URL/slots" | python3 -c \
      'import json,sys; s=json.load(sys.stdin); print(max(s, key=lambda x: x.get("n_prompt_tokens", 0))["id"])' 2>/dev/null)
    [ -n "$ID" ] || exit 0
    curl -sf -m 30 -X POST "$URL/slots/$ID?action=save" \
      -H 'Content-Type: application/json' -d "{\"filename\":\"$FILE\"}" || true
    ;;
  restore)
    [ -f "$DIR/$FILE" ] || exit 0
    # モデルの読み込みが終わるまで待つ（最大 3 分）
    i=0
    until curl -sf -m 2 "$URL/health" >/dev/null; do
      i=$((i + 1)); [ $i -ge 180 ] && exit 0; sleep 1
    done
    curl -sf -m 60 -X POST "$URL/slots/0?action=restore" \
      -H 'Content-Type: application/json' -d "{\"filename\":\"$FILE\"}" || true
    ;;
  *)
    echo "usage: $0 save|restore" >&2; exit 1
    ;;
esac
exit 0
