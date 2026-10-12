#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
[ -f .env ] && [ -f wechat-desktop-bot/config.json ] || {
  echo '尚未初始化，请先 sudo sh setup.sh。' >&2; exit 1;
}
docker compose -f compose.yaml up -d weixin
docker compose -f compose.yaml ps
