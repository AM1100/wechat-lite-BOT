"""Package explicitly allowed source files; never collect deployed runtime data."""
from pathlib import Path
import ast
import hashlib
import json
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CONTRIBUTING.md',
    'SECURITY.md', 'CHANGELOG.md', '.gitignore', '.gitattributes',
    'compose.yaml', 'setup.sh', 'start.sh', 'stop.sh', 'logs.sh',
    'desktop-password.sh', 'reset-admin-password.sh', 'backup.sh',
    'docs/USAGE.md', 'docs/GITHUB_UPLOAD.md', 'prompts/natural-chat.txt',
    'wechat-desktop-bot/main.py', 'wechat-desktop-bot/gui.py',
    'wechat-desktop-bot/admin.py', 'wechat-desktop-bot/style.py',
    'wechat-desktop-bot/probe_chat.py', 'wechat-desktop-bot/config.example.json',
    'wechat-desktop-bot/Dockerfile', 'wechat-desktop-bot/.dockerignore',
    'wechat-desktop-bot/service', 'wechat-desktop-bot/admin-service',
    'wechat-desktop-bot/web/index.html', 'wechat-desktop-bot/web/app.js',
    'wechat-desktop-bot/web/app.css', 'tests/test_bot.py', 'tests/test_queue.py',
    'tests/test_admin.py', 'tests/config.example.json', 'tools/package_release.py',
    '.github/workflows/ci.yml', '.github/ISSUE_TEMPLATE/bug_report.md',
    '.github/pull_request_template.md',
)


def source_bytes():
    result = {}
    for name in FILES:
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or linked source file: ' + name)
        data = path.read_bytes()
        text = data.decode('utf-8')
        if b'\r\n' in data:
            raise ValueError('Use LF line endings: ' + name)
        if re.search(r'\bsk-[A-Za-z0-9_-]{16,}\b', text):
            raise ValueError('Possible API Key: ' + name)
        if re.search(r'^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----$', text, re.MULTILINE):
            raise ValueError('Possible private key: ' + name)
        if name.endswith('config.example.json'):
            c = json.loads(text)
            if c['model']['api_key'] not in ('', 'YOUR_API_KEY'):
                raise ValueError('Example config contains a non-placeholder Key: ' + name)
        if name.endswith('.py'):
            ast.parse(text)
        result[name] = data
    return result


def main():
    files = source_bytes()
    manifest = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                       for name, data in sorted(files.items()))
    files['SHA256SUMS.txt'] = manifest.encode('utf-8')
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    with zipfile.ZipFile(output / 'wechat-lite-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo('wechat-lite/' + name)
            executable = name.endswith('.sh') or name in ('wechat-desktop-bot/service', 'wechat-desktop-bot/admin-service')
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    import io
    with tarfile.open(output / 'wechat-lite-source.tar.gz', 'w:gz') as archive:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo('wechat-lite/' + name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith('.sh') or name in ('wechat-desktop-bot/service', 'wechat-desktop-bot/admin-service') else 0o644
            archive.addfile(info, io.BytesIO(data))
    print('Packaged %d files; config.json, .env, data and personal samples are excluded.' % len(files))
    for name in ('wechat-lite-source.zip', 'wechat-lite-source.tar.gz'):
        print(output / name)


if __name__ == '__main__':
    main()
