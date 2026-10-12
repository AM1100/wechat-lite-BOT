"""Password-protected local web admin, Python standard library only."""
import argparse
import base64
import copy
from contextlib import closing
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import main
from style import own_messages, select_sample, STYLE_PROMPT

MAX_BODY = 1100000
ASSETS = Path(__file__).with_name('web')


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.web-tmp')
    with temp.open('w', encoding='utf-8') as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def init_admin(directory):
    path = Path(directory) / 'admin.json'
    if path.exists():
        print('Admin password already initialized; keeping it.', flush=True)
        return
    password, salt = secrets.token_urlsafe(15), secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 240000)
    atomic_json(path, {'salt': salt.hex(), 'digest': digest.hex()})
    print('网页后台用户名：admin\n初始密码：' + password + '\n请保存此密码。', flush=True)


class AdminServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, directory):
        self.directory = Path(directory)
        self.config_path = self.directory / 'config.json'
        self.lock = threading.RLock()
        self.sessions, self.attempts = {}, {}
        self.analysis_lock = threading.Lock()
        super().__init__(address, Handler)

    def config(self):
        return json.loads(self.config_path.read_text(encoding='utf-8-sig'))

    def public(self, c):
        result = copy.deepcopy(c)
        result['model']['api_key_set'] = bool(c['model']['api_key'] and 'YOUR_' not in c['model']['api_key'])
        result['model']['api_key'] = ''
        return {'config': result, 'version': main.signature(c)}

    def reserve_admin_call(self):
        # Administrative probes/learning are explicitly triggered and separately capped.
        import datetime as dt
        day = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        with self.lock, closing(sqlite3.connect(self.directory / 'admin-usage.sqlite')) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS calls(day TEXT, started REAL, purpose TEXT)')
            total = db.execute('SELECT count(*) FROM calls WHERE day=?', (day,)).fetchone()[0]
            if total >= 10:
                raise ValueError('今天的后台测试和风格分析已达10次上限，请明天再试。')
            db.execute('INSERT INTO calls VALUES(?,?,?)', (day, time.time(), 'manual'))
            db.execute('DELETE FROM calls WHERE started<?', (time.time()-7*86400,))

    def status(self):
        result = {'state': 'unknown', 'event': '等待机器人状态', 'today_calls': 0}
        try:
            runtime = json.loads((self.directory / 'runtime.json').read_text(encoding='utf-8'))
            result.update(runtime)
            if time.time()-runtime['updated_at'] > 180:
                result.update(state='stale', event='近期没有状态更新，请检查机器人进程')
        except (OSError, ValueError, KeyError):
            pass
        try:
            import datetime as dt
            day = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
            dbpath = self.directory / 'state.sqlite'
            if dbpath.exists():
                with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro', uri=True, timeout=1)) as db:
                    result['today_calls'] = db.execute('SELECT count(*) FROM calls WHERE day=?', (day,)).fetchone()[0]
        except sqlite3.Error:
            pass
        try:
            result['sample'] = json.loads((self.directory / 'sample.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            result['sample'] = None
        return result


class Handler(BaseHTTPRequestHandler):
    server_version = 'WeChatAdmin'

    def log_message(self, fmt, *args):
        pass  # no credentials, record contents or full request URLs in access logs

    def send(self, status, value, content_type='application/json; charset=utf-8', cookie=None):
        body = json.dumps(value, ensure_ascii=False).encode() if not isinstance(value, bytes) else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def origin_valid(self):
        origin = self.headers.get('Origin')
        return not origin or urlsplit(origin).netloc == self.headers.get('Host')

    def session(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookie['wc_admin'].value
            session = self.server.sessions.get(token)
            if session and session['expires'] > time.time():
                return token, session
        except (KeyError, ValueError):
            pass
        return None, None

    def body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= MAX_BODY:
            raise ValueError('提交内容过大或为空；样本文件上限500KB。')
        if not self.headers.get('Content-Type', '').startswith('application/json'):
            raise ValueError('仅接受JSON请求。')
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError('请求必须是对象。')
        return value

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ('/', '/app.js', '/app.css'):
            filename = {'/':'index.html','/app.js':'app.js','/app.css':'app.css'}[path]
            mime = {'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8',
                    '/app.css':'text/css; charset=utf-8'}[path]
            return self.send(200, (ASSETS / filename).read_bytes(), mime)
        token, session = self.session()
        if not session:
            return self.send(401, {'error':'请先登录。'})
        try:
            if path == '/api/state':
                return self.send(200, {**self.server.public(self.server.config()),
                                       'status': self.server.status(), 'csrf': session['csrf']})
            if path == '/api/status':
                return self.send(200, self.server.status())
            self.send(404, {'error':'页面不存在。'})
        except (OSError, ValueError):
            self.send(500, {'error':'读取配置失败，请检查config.json。'})

    def do_POST(self):
        path = urlsplit(self.path).path
        if not self.origin_valid():
            return self.send(403, {'error':'请求来源不匹配。'})
        try:
            value = self.body()
            if path == '/api/login':
                return self.login(value)
            token, session = self.session()
            if not session:
                return self.send(401, {'error':'请先登录。'})
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
                return self.send(403, {'error':'请刷新页面后重试。'})
            if path == '/api/logout':
                self.server.sessions.pop(token, None)
                return self.send(200, {'ok':True}, cookie='wc_admin=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict')
            if path == '/api/config':
                return self.save_config(value)
            if path == '/api/test':
                return self.test_model()
            if path == '/api/sample':
                return self.upload(value)
            if path == '/api/sample/delete':
                with self.server.lock:
                    for filename in ('sample.txt', 'sample.json'):
                        (self.server.directory / filename).unlink(missing_ok=True)
                return self.send(200, {'ok':True})
            if path == '/api/style/analyze':
                return self.analyze(value)
            if path == '/api/password':
                password = value.get('password', '')
                if not isinstance(password, str) or not 12 <= len(password) <= 128:
                    raise ValueError('新密码长度需为12至128个字符。')
                salt = secrets.token_bytes(16)
                digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 240000)
                with self.server.lock:
                    atomic_json(self.server.directory / 'admin.json', {'salt':salt.hex(),'digest':digest.hex()})
                    self.server.sessions.clear()
                return self.send(200, {'ok':True})
            self.send(404, {'error':'接口不存在。'})
        except (ValueError, KeyError, TypeError) as exc:
            self.send(400, {'error':str(exc)[:250]})
        except HTTPError as exc:
            error = main.http_failure(exc, self.server.config()['model'])
            self.send(502, {'error':str(error)[:350]})
        except main.ModelConnectionError as exc:
            self.send(502, {'error':str(exc)[:350]})
        except Exception as exc:
            self.send(502, {'error':'操作失败（'+type(exc).__name__+'），请检查模型连接或容器文件权限。'})

    def login(self, value):
        peer, now = self.client_address[0], time.time()
        with self.server.lock:
            tries = [t for t in self.server.attempts.get(peer, []) if now-t < 300]
            if len(tries) >= 8:
                return self.send(429, {'error':'尝试过多，请5分钟后重试。'})
            tries.append(now)
            self.server.attempts[peer] = tries
        password = value.get('password', '')
        if not isinstance(password, str) or len(password) > 128:
            raise ValueError('密码无效。')
        record = json.loads((self.server.directory / 'admin.json').read_text(encoding='utf-8'))
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(record['salt']), 240000).hex()
        if value.get('username') != 'admin' or not hmac.compare_digest(actual, record['digest']):
            return self.send(401, {'error':'用户名或密码不正确。'})
        token = secrets.token_urlsafe(32)
        with self.server.lock:
            self.server.attempts.pop(peer, None)
            self.server.sessions = {k:v for k,v in self.server.sessions.items() if v['expires'] > now}
            self.server.sessions[token] = {'csrf':secrets.token_urlsafe(24),'expires':now+12*3600}
        self.send(200, {'ok':True}, cookie='wc_admin='+token+'; Path=/; Max-Age=43200; HttpOnly; SameSite=Strict')

    def save_config(self, value):
        with self.server.lock:
            old = self.server.config()
            if value.get('version') != main.signature(old):
                return self.send(409, {'error':'配置已在其他地方修改。请刷新页面再保存。'})
            c = value['config']
            if not isinstance(c, dict):
                raise ValueError('配置格式错误。')
            c = copy.deepcopy(c)
            if not c['model'].get('api_key'):
                c['model']['api_key'] = old['model']['api_key']
            c['model'].pop('api_key_set', None)
            main.validate_config(c)
            atomic_json(self.server.config_path, c)
        self.send(200, {**self.server.public(c), 'ok':True})

    def test_model(self):
        c = self.server.config()
        self.check_model(c)
        self.server.reserve_admin_call()
        c = copy.deepcopy(c)
        c['model']['system_prompt'] = '只回答OK。'
        c['model']['style_profile'] = ''
        c['reply_max_chars'] = 30
        reply = main.model_reply('连接测试，请回答OK。', [], c)
        self.send(200, {'ok':True, 'reply':reply})

    def check_model(self, c):
        m = c['model']
        if any(not m[k] or 'YOUR_' in m[k] for k in ('base_url', 'api_key', 'name')):
            raise ValueError('请先保存API地址、Key和模型名。')
        main.validate_config({**c, 'enabled':False})
        url = urlsplit(m['base_url'])
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password:
            raise ValueError('API地址格式不正确。')

    def upload(self, value):
        text = value.get('text', '')
        if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > 500000:
            raise ValueError('请上传非空文字文件，转换UTF-8后不超过500KB。')
        lines = own_messages(text, '', own_only=True)
        sample = select_sample(lines)
        meta = {'filename':str(value.get('filename', '我的消息.txt'))[:120],
                'chars':len(text),'lines':len(lines),'sample_chars':len(sample),'uploaded_at':time.time()}
        with self.server.lock:
            target = self.server.directory / 'sample.txt'
            temp = target.with_suffix('.upload-tmp')
            temp.write_text(text, encoding='utf-8')
            os.chmod(temp, 0o600)
            os.replace(temp, target)
            atomic_json(self.server.directory / 'sample.json', meta)
        self.send(200, {'ok':True, 'sample':meta, 'preview':sample[:800]})

    def analyze(self, value):
        if not self.server.analysis_lock.acquire(blocking=False):
            return self.send(409, {'error':'风格分析正在进行，请稍等。'})
        try:
            with self.server.lock:
                c = self.server.config()
                text = (self.server.directory / 'sample.txt').read_text(encoding='utf-8')
            self.check_model(c)
            sample = select_sample(own_messages(text, '', own_only=True))
            if len(sample) < 20:
                raise ValueError('样本太短，请提供至少20个字符。')
            self.server.reserve_admin_call()
            m = c['model']
            body = {**m['extra_body'], 'model':m['name'], 'stream':False,
                    m['output_limit_field']:600,
                    'messages':[{'role':'system','content':STYLE_PROMPT},
                                {'role':'user','content':'以下是我发出的消息样本：\n<samples>\n'+sample+'\n</samples>'}]}
            base = m['base_url'].rstrip('/')
            url = base if base.endswith('/chat/completions') else base+'/chat/completions'
            request = Request(url, data=json.dumps(body, ensure_ascii=False).encode(),
                              headers={'Content-Type':'application/json','Authorization':'Bearer '+m['api_key']})
            with urlopen(request, timeout=m['timeout_seconds']) as response:
                result = json.loads(response.read(2*1024*1024))
            profile = result['choices'][0]['message']['content']
            if not isinstance(profile, str) or not profile.strip():
                raise ValueError('模型没有返回风格描述。')
            self.send(200, {'profile':profile.strip()[:main.STYLE_MAX_CHARS], 'usage':result.get('usage') or {},
                            'sample_chars':len(sample)})
        finally:
            self.server.analysis_lock.release()


def run_server(directory, host='0.0.0.0', port=8787):
    init_admin(directory)
    server = AdminServer((host, port), directory)
    print('Web admin listening on port '+str(server.server_port), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default=str(Path(__file__).parent))
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--init', action='store_true')
    args = parser.parse_args()
    if args.init:
        init_admin(args.directory)
    else:
        run_server(args.directory, args.host, args.port)
