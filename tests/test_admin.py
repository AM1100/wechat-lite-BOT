import copy
import hashlib
import http.client
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'wechat-desktop-bot'))
import secrets
import tempfile
import threading
import unittest
from unittest.mock import patch
import admin
import main
from style import own_messages, select_sample


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.config = main.read_config(Path(__file__).with_name('config.example.json'))
        self.config['model'].update(api_key='secret-original-key', base_url='https://model.invalid/v1', name='test-model')
        admin.atomic_json(self.directory / 'config.json', self.config)
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac('sha256', b'long-test-password', salt, 240000).hex()
        admin.atomic_json(self.directory / 'admin.json', {'salt':salt.hex(),'digest':digest})
        self.server = admin.AdminServer(('127.0.0.1',0), self.directory)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = self.csrf = ''

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def call(self, method, path, value=None, **headers):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        h = {'Cookie':self.cookie, 'X-CSRF-Token':self.csrf, **headers}
        if value is not None:
            h['Content-Type'] = 'application/json'
        connection.request(method, path, None if value is None else json.dumps(value), h)
        response = connection.getresponse()
        body = response.read()
        cookie = response.getheader('Set-Cookie')
        result = (response.status, json.loads(body) if body.startswith(b'{') else body, cookie)
        connection.close()
        return result

    def login(self):
        code, value, cookie = self.call('POST','/api/login',{'username':'admin','password':'long-test-password'})
        self.assertEqual(code,200)
        self.cookie = cookie.split(';')[0]
        code, value, _ = self.call('GET','/api/state')
        self.csrf = value['csrf']
        return value

    def test_unauthenticated_access_and_no_key_disclosure(self):
        self.assertEqual(self.call('GET','/api/state')[0],401)
        state = self.login()
        self.assertNotIn('secret-original-key',json.dumps(state))
        self.assertTrue(state['config']['model']['api_key_set'])

    def test_save_preserves_key_and_sets_whitelist_and_style(self):
        state = self.login()
        c = state['config']
        c['allowed_private_chats'] = ['测试好友A','测试好友B']
        c['model']['style_profile'] = '短句，口语化'
        c['global_request_interval_seconds'] = 10
        code, result, _ = self.call('POST','/api/config',{'version':state['version'],'config':c})
        self.assertEqual(code,200)
        saved = self.server.config()
        self.assertEqual(saved['model']['api_key'],'secret-original-key')
        self.assertEqual(saved['allowed_private_chats'],['测试好友A','测试好友B'])
        self.assertEqual(saved['model']['style_profile'],'短句，口语化')
        self.assertEqual(saved['global_request_interval_seconds'],10)

    def test_long_prompts_save_without_truncation_and_preserve_key(self):
        state = self.login()
        c = state['config']
        c['model']['style_profile'] = '口语' * 5000
        c['model']['system_prompt'] = '自然' * 5000
        code, result, _ = self.call('POST','/api/config',{'version':state['version'],'config':c})
        self.assertEqual(code, 200)
        saved = self.server.config()
        self.assertEqual(saved['model']['style_profile'], c['model']['style_profile'])
        self.assertEqual(saved['model']['system_prompt'], c['model']['system_prompt'])
        self.assertEqual(saved['model']['api_key'], 'secret-original-key')

    def test_overlong_prompt_rejected_without_changing_saved_config(self):
        state = self.login()
        before = self.server.config()
        for field in ('style_profile', 'system_prompt'):
            with self.subTest(field=field):
                c = copy.deepcopy(state['config'])
                c['model'][field] = '字' * 10001
                code, result, _ = self.call('POST','/api/config',{'version':state['version'],'config':c})
                self.assertEqual(code, 400)
                self.assertIn('10000', result['error'])
                self.assertEqual(self.server.config(), before)

    def test_model_error_details_and_saved_output_limit_are_preserved(self):
        self.login()
        with patch('main.model_reply', side_effect=main.ModelRateLimitError('HTTP status=429 RPM limit')) as model:
            code, value, _ = self.call('POST','/api/test',{})
        self.assertEqual(code,502)
        self.assertIn('RPM limit', value['error'])
        self.assertEqual(model.call_args.args[2]['model']['max_output_tokens'], self.config['model']['max_output_tokens'])

    def test_conflict_does_not_overwrite_config(self):
        state = self.login()
        c = self.server.config()
        c['poll_seconds']=5
        admin.atomic_json(self.directory / 'config.json',c)
        self.assertEqual(self.call('POST','/api/config',{'version':state['version'],'config':state['config']})[0],409)
        self.assertEqual(self.server.config()['poll_seconds'],5)

    def test_csrf_and_foreign_origin_rejected(self):
        state = self.login()
        self.csrf='wrong'
        self.assertEqual(self.call('POST','/api/config',{'version':state['version'],'config':state['config']})[0],403)
        self.assertEqual(self.call('POST','/api/login',{},Origin='https://evil.invalid')[0],403)

    def test_invalid_config_not_saved(self):
        state = self.login()
        state['config']['model']['extra_body']={'tools':[]}
        self.assertEqual(self.call('POST','/api/config',{'version':state['version'],'config':state['config']})[0],400)
        self.assertEqual(self.server.config()['model']['extra_body'],{})

    def test_upload_is_local_and_never_calls_model(self):
        self.login()
        with patch('admin.urlopen') as http:
            code, value, _ = self.call('POST','/api/sample',{'filename':'我的话.txt','text':'你好呀\n我喜欢直接说话\n不用固定格式'})
        self.assertEqual(code,200)
        http.assert_not_called()
        self.assertEqual(value['sample']['lines'],3)
        self.assertTrue((self.directory / 'sample.txt').exists())
        self.assertEqual(self.call('POST','/api/sample/delete',{})[0],200)
        self.assertFalse((self.directory / 'sample.txt').exists())

    def test_style_analysis_one_request_bounded_and_requires_explicit_save(self):
        self.login()
        self.call('POST','/api/sample',{'text':'我的表达习惯样本很长啊。\n'*5000})
        from unittest.mock import MagicMock
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'message':{'content':'短句，随意，少用标点'}}]}).encode()
        with patch('admin.urlopen',return_value=response) as http:
            code, value, _ = self.call('POST','/api/style/analyze',{})
        self.assertEqual(code,200)
        http.assert_called_once()
        body=json.loads(http.call_args.args[0].data)
        self.assertLessEqual(value['sample_chars'],6000)
        self.assertEqual(body['max_tokens'],600)
        self.assertEqual(self.server.config()['model'].get('style_profile',''),'')

    def test_admin_request_budget(self):
        for _ in range(10):
            self.server.reserve_admin_call()
        with self.assertRaises(ValueError):
            self.server.reserve_admin_call()

    def test_login_rate_limit(self):
        for _ in range(8):
            self.assertEqual(self.call('POST','/api/login',{'username':'admin','password':'wrong'})[0],401)
        self.assertEqual(self.call('POST','/api/login',{'username':'admin','password':'wrong'})[0],429)

    def test_password_change_invalidates_existing_session(self):
        self.login()
        self.assertEqual(self.call('POST','/api/password',{'password':'a-new-long-password'})[0],200)
        self.assertEqual(self.call('GET','/api/state')[0],401)
        self.assertEqual(self.call('POST','/api/login',{'username':'admin','password':'long-test-password'})[0],401)
        self.assertEqual(self.call('POST','/api/login',{'username':'admin','password':'a-new-long-password'})[0],200)

    def test_static_routes_and_unknown_route(self):
        self.assertEqual(self.call('GET','/')[0],200)
        self.assertEqual(self.call('GET','/app.js')[0],200)
        self.assertEqual(self.call('GET','/../../admin.json')[0],401)


class StyleTests(unittest.TestCase):
    def test_plain_owner_messages_need_no_sender_labels(self):
        self.assertEqual(own_messages('今天忙不忙\n\n行，我等你', '', own_only=True),['今天忙不忙','行，我等你'])

    def test_sampling_spans_export_and_limits_request(self):
        messages=['message '+str(i)+'x'*500 for i in range(1000)]
        sample=select_sample(messages)
        self.assertLessEqual(len(sample),6000)
        self.assertIn('message 0',sample)
        self.assertIn('message 999',sample)


if __name__ == '__main__':
    unittest.main()
