#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
docker compose -f compose.yaml exec -T -u abc -w /config/wechat-lite weixin python3 - <<'PY'
from pathlib import Path
import hashlib, secrets, shutil, time
from admin import atomic_json
p = Path('/config/wechat-lite/admin.json')
if p.exists():
    shutil.copy2(p, p.with_name('admin-backup-' + str(time.time_ns()) + '.json'))
password = secrets.token_urlsafe(15)
salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 240000).hex()
atomic_json(p, {'salt': salt.hex(), 'digest': digest})
print('后台用户名：admin')
print('新后台密码：' + password)
PY
docker compose -f compose.yaml exec -T -u abc weixin pkill -TERM -f '^python3 -u /config/wechat-lite/admin.py$' || true
echo '请保存新密码，等几秒后重新登录。'
