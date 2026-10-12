#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ "$(id -u)" -ne 0 ]; then
  echo '请用 sudo sh setup.sh 或 root 账号安装。' >&2
  exit 1
fi
command -v docker >/dev/null 2>&1 || { echo '请先安装 Docker Engine。' >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo '请先安装 Docker Compose v2 插件。' >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo 'Docker 没有运行，请执行 systemctl start docker。' >&2; exit 1; }
case "$(uname -m)" in
  x86_64) ;;
  aarch64|arm64) echo 'ARM64 需要验证微信控件；本程序目前只在 x86-64 环境验证过。' ;;
  *) echo '需要 64 位 x86 或 ARM Linux。' >&2; exit 1 ;;
esac
umask 077
if [ ! -f .env ]; then
  command -v openssl >/dev/null 2>&1 || { echo '请执行 apt-get install openssl。' >&2; exit 1; }
  desktop_secret=$(openssl rand -hex 24)
  printf 'WECHAT_DESKTOP_PASSWORD=%s\n' "$desktop_secret" > .env
fi
if [ ! -f wechat-desktop-bot/config.json ]; then
  cp wechat-desktop-bot/config.example.json wechat-desktop-bot/config.json
fi
mkdir -p data
chown -R 1000:1000 wechat-desktop-bot
chown 1000:1000 data
chmod 600 .env wechat-desktop-bot/config.json
docker compose -f compose.yaml config --quiet
docker compose -f compose.yaml build weixin
docker compose -f compose.yaml up -d weixin
echo '安装完成；再次运行 setup.sh 会保留已有配置和密码。'
echo '远程桌面用户名：wechat。查询密码：sh desktop-password.sh'
echo '后台用户名：admin。初始密码见下面日志；忘记可执行 sh reset-admin-password.sh'
sleep 3
docker compose -f compose.yaml logs --tail=200 weixin
echo '请按 README.md 建立 SSH 隧道，登录微信和管理后台。默认仅监听、不发送。'
