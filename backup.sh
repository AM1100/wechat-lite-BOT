#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo '请执行 sudo sh backup.sh。' >&2; exit 1; }
[ -f .env ] && [ -f wechat-desktop-bot/config.json ] || { echo '请先完成安装。' >&2; exit 1; }
umask 077
mkdir -p backups
backup_file="$PWD/backups/wechat-backup-$(date +%Y%m%d-%H%M%S)-$$.tar.gz"
echo '正在停止微信和机器人以备份一致的数据，完成后重新启动。'
docker compose -f compose.yaml stop weixin
resume() { docker compose -f compose.yaml up -d weixin; }
trap resume 0
tar -czf "$backup_file" .env compose.yaml data wechat-desktop-bot prompts
chmod 600 "$backup_file"
echo "备份完成：$backup_file"
echo '备份包含 API Key、桌面密码及微信数据，请私下保存。'
