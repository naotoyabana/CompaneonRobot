#!/usr/bin/env bash
# ~/stackchan-src のファームをビルドし、~/stackchan-kit/firmware/out/ に .bin を置く。
# 書き込みはそのあと ~/stackchan-kit/firmware/flash.sh で行う。
#   ./build-dev.sh <server-ip>     例：./build-dev.sh 192.168.11.51
set -euo pipefail
SERVER_IP="${1:?使い方: $0 <server-ip>}"
SRC="${SRC:-$HOME/stackchan-src}"
OUT="$HOME/stackchan-kit/firmware/out"
IDF_IMAGE="espressif/idf:v5.5.4"

# スタックチャンが起動時に問い合わせる住所（build.sh と同じ設定）。
# sdkconfig.defaults.* は sdkconfig が無いときにしか読まれないので、
# 中身が変わったときだけ sdkconfig を消して作り直させる（毎回消すと全部ビルドし直しになる）。
DEFAULTS="$SRC/firmware/sdkconfig.defaults.local"
# STACKCHAN_SERVER_URL は「体の電話」（WS-Avatar）の相手先＝自作の体サーバー（body/server.py、ポート 8100）。
# 元のキットは http://127.0.0.1:9（無効）にしていた。
NEW=$(printf 'CONFIG_OTA_URL="http://%s:8003/xiaozhi/ota/"\nCONFIG_STACKCHAN_SERVER_URL="http://%s:8100"\n' "$SERVER_IP" "$SERVER_IP")
if [ "$(cat "$DEFAULTS" 2>/dev/null)" != "$NEW" ]; then
  printf '%s\n' "$NEW" > "$DEFAULTS"
  rm -f "$SRC/firmware/sdkconfig"
fi

docker run --rm -v "$SRC:/src" -v "$OUT:/out" -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  "$IDF_IMAGE" bash -euo pipefail -c '
    git config --global --add safe.directory "*"
    cd /src/firmware
    trap "chown -R \$HOST_UID:\$HOST_GID /src /out" EXIT
    idf.py build
    cp build/bootloader/bootloader.bin build/partition_table/partition-table.bin \
       build/ota_data_initial.bin build/stack-chan.bin build/generated_assets.bin /out/
  '
echo "server $SERVER_IP (dev)" > "$OUT/mode.txt"
# grep -m1 だと strings が途中で切られて（SIGPIPE）pipefail で失敗扱いになるので、全部読ませる
strings "$OUT/stack-chan.bin" | grep xiaozhi/ota || true
echo "ビルド完了。書き込み：~/stackchan-kit/firmware/flash.sh"
