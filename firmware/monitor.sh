#!/usr/bin/env bash
# USB でつないだスタックチャンのログ（ファームの中の ESP_LOGI など）を表示し、ファイルにも残す。
#   ./monitor.sh [serial-port]      (default: /dev/ttyACM0)
# 終わるときは Ctrl+C。
# USB が切れても、つながり直すのを待って読み続ける。
set -euo pipefail
PORT="${1:-/dev/ttyACM0}"
LOGDIR="$(cd "$(dirname "$0")" && pwd)/logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/serial-$(date +%Y%m%d-%H%M%S).log"
# esptool（pipx）の中に入っている pyserial を使う
PY="$HOME/.local/share/pipx/venvs/esptool/bin/python"
echo "ログ: $LOG （Ctrl+C で終了）"
exec "$PY" -u - "$PORT" "$LOG" <<'EOF'
import sys, time, serial
port, log = sys.argv[1], sys.argv[2]
# DTR/RTS（信号線）には触らない。開いたときに両方オンになるのはそのままで大丈夫。
# 片方ずつ切り替えると、途中で ESP32 の「リセット」の合図になり、再起動してしまう。
with open(log, "ab") as f:
    def note(msg):
        line = f"\n[monitor] {time.strftime('%H:%M:%S')} {msg}\n".encode()
        sys.stdout.buffer.write(line); sys.stdout.flush(); f.write(line); f.flush()
    try:
        while True:
            try:
                s = serial.Serial(port, 115200, timeout=0.2)
            except serial.SerialException:
                time.sleep(0.5)  # USB がまだ戻っていない
                continue
            note("つながった")
            try:
                while True:
                    data = s.read(4096)
                    if data:
                        sys.stdout.buffer.write(data); sys.stdout.flush()
                        f.write(data); f.flush()
            except (serial.SerialException, OSError):
                note("USB が切れた。つながり直すのを待つ")
                s.close()
    except KeyboardInterrupt:
        pass
EOF
