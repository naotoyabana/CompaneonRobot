#!/usr/bin/env bash
# ファームのソースを ~/stackchan-src に置く（1 回だけ実行する）。
# ~/stackchan-kit/firmware/build.sh と同じ版・同じパッチを使うが、
# コンテナを捨ててもソースが残るように、ホストのフォルダで作業する。
set -euo pipefail
SRC="${SRC:-$HOME/stackchan-src}"
KIT="$HOME/stackchan-kit/firmware"
UPSTREAM_REPO="https://github.com/m5stack/StackChan.git"
UPSTREAM_COMMIT="eff0d6b5109663faec8f1d98848b4b0e5246bbfc"   # build.sh と同じ
IDF_IMAGE="espressif/idf:v5.5.4"

[ -e "$SRC" ] && { echo "$SRC はもうある。やり直すなら消してから実行する" >&2; exit 1; }
git clone -q "$UPSTREAM_REPO" "$SRC"
git -C "$SRC" checkout -q -b dev "$UPSTREAM_COMMIT"
git -C "$SRC" apply "$KIT/stackchan-kit.patch"

# xiaozhi-esp32 の取得と managed_components の準備は ESP-IDF が要るのでコンテナで行う
docker run --rm -v "$SRC:/src" -v "$KIT:/kit:ro" -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  "$IDF_IMAGE" bash -euo pipefail -c '
    git config --global --add safe.directory "*"
    cd /src/firmware
    python3 fetch_repos.py
    git -C xiaozhi-esp32 apply /kit/xiaozhi-kit.patch
    idf.py reconfigure >/dev/null
    patch -p1 -d managed_components/78__esp-ml307 < /kit/esp-ml307-kit.patch
    chown -R "$HOST_UID:$HOST_GID" /src
  '

# 「元のコード＋キットのパッチ」を基準としてコミットしておく。
# 以後の自分の変更は git diff で見える。コミットはこの PC の中だけ（上流には push しない）。
for repo in "$SRC" "$SRC/firmware/xiaozhi-esp32"; do
  git -C "$repo" config user.name naotoyabana
  git -C "$repo" config user.email "302033915+naotoyabana@users.noreply.github.com"
  git -C "$repo" add -A
  git -C "$repo" commit -q -m "baseline: upstream + stackchan-kit patches"
done
echo "完了：$SRC"
