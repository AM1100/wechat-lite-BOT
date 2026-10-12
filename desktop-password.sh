#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
echo '远程桌面用户名：wechat'
grep '^WECHAT_DESKTOP_PASSWORD=' .env
