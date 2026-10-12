import json
import io
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'wechat-desktop-bot'))
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import main
from gui import classify, Gui


class BotTests(unittest.TestCase):
    def config(self):
        return main.read_config(Path(__file__).with_name('config.example.json'))

    def test_sample_incoming(self):
        sample = {'green_samples_left_right': [0, 0], 'common_rgb_left': [([232,232,240],149)]}
        self.assertEqual(classify('收到测试', sample), 'in')

    def test_sample_outgoing(self):
        self.assertEqual(classify('发出测试', {'green_samples_left_right':[0,170]}), 'out')

    def test_sticker_green_is_never_text(self):
        self.assertEqual(classify('Animated Stickers [你好]', {'green_samples_left_right':[0,69]}), 'ignore')
        self.assertEqual(classify('18:26', {}), 'ignore')

    def test_unknown_and_clipped_are_not_incoming(self):
        self.assertEqual(classify('hello', {}), 'unknown')
        self.assertEqual(classify('hello', {'status':'clipped_or_offscreen'}), 'unknown')

    def test_baseline_and_repeat_texts(self):
        tracker = main.Tracker()
        row = ('in','hello')
        self.assertIsNone(tracker.update('friend',[row]))
        self.assertEqual(tracker.update('friend',[row,row]),[row])
        self.assertEqual(tracker.update('friend',[row,row]),[])

    def test_shifted_viewport_and_no_overlap(self):
        a, b, c = [('in',v) for v in ('a','b','c')]
        self.assertEqual(main.suffix_new([a,b],[b,c]),[c])
        self.assertIsNone(main.suffix_new([a],[c]))

    def test_first_new_message_in_previously_empty_chat(self):
        tracker = main.Tracker()
        self.assertIsNone(tracker.update('f',[]))
        self.assertEqual(tracker.update('f',[('in','new')]),[('in','new')])

    def test_sender_stops_for_changed_chat_or_existing_draft(self):
        gui = Gui.__new__(Gui)
        gui.click = MagicMock()
        gui.scan = MagicMock(return_value={'name':'someone else','draft':'','rows':[]})
        with self.assertRaises(RuntimeError):
            gui.send_reply('friend','reply',[],lambda:True)
        gui.scan.return_value = {'name':'friend','draft':'my draft','rows':[]}
        with self.assertRaises(RuntimeError):
            gui.send_reply('friend','reply',[],lambda:True)
        gui.click.assert_not_called()

    def test_manual_outgoing_during_draft_insertion_prevents_send(self):
        gui = Gui.__new__(Gui)
        gui.click = MagicMock()
        editor = MagicMock()
        editor.get_editable_text_iface.return_value.set_text_contents.return_value=True
        gui.scan = MagicMock(side_effect=[
            {'name':'friend','draft':'','rows':[],'editor':editor},
            {'name':'friend','draft':'reply','rows':[('out','manual')],'editor':editor}])
        with patch('gui.time.sleep'):
            with self.assertRaises(RuntimeError):
                gui.send_reply('friend','reply',[],lambda:True)
        gui.click.assert_not_called()

    def test_incoming_burst_during_typing_can_send_once_and_ack_new_reply(self):
        adapter = Gui.__new__(Gui)
        adapter.click = MagicMock()
        adapter.rect = MagicMock(return_value=(0,0,40,30))
        adapter.A = MagicMock()
        editor, button = MagicMock(), MagicMock()
        editor.get_editable_text_iface.return_value.set_text_contents.return_value = True
        button.get_state_set.return_value.contains.return_value = True
        adapter.scan = MagicMock(side_effect=[
            {'name':'f','draft':'','rows':[('in','first'),('in','second')],'editor':editor},
            {'name':'f','draft':'reply','rows':[('in','first'),('in','second'),('in','third')], 'editor':editor,'send':button},
            {'name':'f','draft':'','rows':[('in','second'),('in','third'),('out','reply'),('in','fourth')]}])
        with patch('gui.time.sleep'):
            result = adapter.send_reply('f','reply',[('in','first')],lambda:True)
        self.assertEqual(result['rows'][-1], ('in','fourth'))
        adapter.click.assert_called_once()

    def test_tracker_ignores_timestamps_and_tolerates_unknown_repainting(self):
        tracker = main.Tracker()
        tracker.update('f',[('in','first'),('ignore','12:00')])
        self.assertEqual(tracker.update('f',[('unknown','first'),('ignore','12:01'),('in','second')]), [('in','second')])
        self.assertIsNone(main.suffix_new([('in','first')],[('out','first')]))

    def test_disabled_send_button_clears_only_verified_bot_draft(self):
        from gui import SendDeferred
        adapter = Gui.__new__(Gui)
        adapter.A = MagicMock()
        adapter.click = MagicMock()
        editor, button = MagicMock(), MagicMock()
        editor.get_editable_text_iface.return_value.set_text_contents.return_value = True
        button.get_state_set.return_value.contains.return_value = False
        adapter.scan = MagicMock(side_effect=[
            {'name':'f','draft':'','rows':[],'editor':editor},
            {'name':'f','draft':'reply','rows':[],'editor':editor,'send':button}])
        with patch('gui.time.sleep'), self.assertRaises(SendDeferred):
            adapter.send_reply('f','reply',[],lambda:True)
        self.assertEqual([c.args[0] for c in editor.get_editable_text_iface.return_value.set_text_contents.call_args_list], ['reply',''])
        adapter.click.assert_not_called()

    def test_existing_equal_reply_does_not_confirm_a_new_send(self):
        before = [('out','same'),('in','first')]
        self.assertFalse(main.reply_observed(before, {'draft':'','rows':before}, 'same'))
        self.assertTrue(main.reply_observed(before, {'draft':'','rows':before+[('out','same')]}, 'same'))

    def test_scan_error_after_click_is_uncertain_and_never_clicks_twice(self):
        from gui import SendUncertain
        adapter = Gui.__new__(Gui)
        adapter.A = MagicMock()
        adapter.click = MagicMock()
        adapter.rect = MagicMock(return_value=(0,0,40,30))
        editor, button = MagicMock(), MagicMock()
        editor.get_editable_text_iface.return_value.set_text_contents.return_value = True
        button.get_state_set.return_value.contains.return_value = True
        adapter.scan = MagicMock(side_effect=[
            {'name':'f','draft':'','rows':[('in','first')],'editor':editor},
            {'name':'f','draft':'reply','rows':[('in','first')],'editor':editor,'send':button},
            RuntimeError('temporary GUI render failure')])
        with patch('gui.time.sleep'), self.assertRaises(SendUncertain) as caught:
            adapter.send_reply('f','reply',[('in','first')],lambda:True)
        self.assertEqual(caught.exception.rows, [('in','first')])
        adapter.click.assert_called_once()

    def test_paused_config_prevents_draft_and_send(self):
        gui = Gui.__new__(Gui)
        gui.click = MagicMock()
        gui.scan = MagicMock(return_value={'name':'friend','draft':'','rows':[]})
        with self.assertRaises(RuntimeError):
            gui.send_reply('friend','reply',[],lambda:False)
        gui.click.assert_not_called()

    def test_draft_reads_text_interface_without_accessible_method_collision(self):
        def node(role, name, rect):
            n = MagicMock()
            n.get_role_name.return_value = role
            n.get_name.return_value = name
            n.get_child_count.return_value = 0
            n.get_child_at_index.return_value = None
            n.get_state_set.return_value.contains.return_value = True
            n.get_component_iface.return_value.get_extents.return_value = SimpleNamespace(
                x=rect[0],y=rect[1],width=rect[2],height=rect[3])
            return n
        listing = node('list','Messages',(80,40,500,400))
        editor = node('text','friend',(80,450,500,80))
        send = node('button','Send',(400,550,50,30))
        chats = node('list','Chats',(0,40,80,400))
        header = node('label','friend',(80,10,100,20))
        app = node('application','wechat',(0,0,0,0))
        children = [listing,editor,send,chats,header]
        app.get_child_count.return_value = len(children)
        app.get_child_at_index.side_effect = lambda i: children[i] if i < len(children) else None
        # A valid old index path can now lead to an unrelated subtree. Root discovery
        # must still find the chat controls in the app's other children.
        decoration = node('filler','',(0,0,0,0))
        decoration.get_child_count.return_value=2
        decoration.get_child_at_index.return_value=decoration
        children.insert(0, decoration)
        app.get_child_count.return_value=len(children)
        text = editor.get_text_iface.return_value
        text.get_character_count.return_value = 0
        text.get_text.side_effect = TypeError('Accessible.get_text takes no offsets')
        gui = Gui.__new__(Gui)
        gui.app = app
        gui.A = MagicMock()
        gui.A.Text.get_text.return_value = ''
        self.assertEqual(gui.scan()['draft'],'')
        gui.A.Text.get_text.assert_called_once_with(text,0,0)
        text.get_text.assert_not_called()

    def test_reserved_attempts_count_and_daily_reset(self):
        c = self.config()
        c['max_requests_per_day'] = c['max_requests_per_friend_per_day'] = 1
        store = main.Store(':memory:')
        self.assertTrue(store.reserve('friend',c,100000))
        self.assertFalse(store.reserve('friend',c,100100))
        self.assertTrue(store.reserve('friend',c,100000+86400))

    def test_history_limits_and_idle_clear(self):
        c = self.config()
        store = main.Store(':memory:')
        with patch('main.time.time',return_value=100):
            store.record('f','hello','reply')
        self.assertEqual(len(store.context('f',c,101)),2)
        c['history_max_chars']=3
        self.assertEqual(store.context('f',c,101),[])
        self.assertEqual(store.context('f',self.config(),10000),[])

    def test_model_single_request_and_bounded_output(self):
        c = self.config()
        c['reply_max_chars']=3
        c['model']['base_url']='https://test.invalid/v1/'
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            'choices':[{'message':{'content':'abcdef'}}],
            'usage':{'prompt_tokens':5,'completion_tokens':6}}).encode()
        with patch('main.urlopen',return_value=response) as call:
            self.assertEqual(main.model_reply('hello',[],c),'abc')
        call.assert_called_once()
        request = call.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url,'https://test.invalid/v1/chat/completions')
        self.assertEqual(body['max_tokens'],180)
        self.assertNotIn('tools',body)

    def test_reply_format_removes_empty_lines_and_preserves_single_newlines(self):
        self.assertEqual(main.normalize_reply('  行\r\n\r\n \t\r\n我看看\n\n\n再说  ',250), '行\n我看看\n再说')
        self.assertEqual(main.normalize_reply('行，我看看',250), '行，我看看')
        self.assertEqual(main.normalize_reply('第一句\u2028\u2028第二句',250), '第一句\n第二句')
        self.assertEqual(main.normalize_reply('你好\n\n朋友',3), '你好')

    def test_model_failure_has_no_retry(self):
        with patch('main.urlopen',side_effect=TimeoutError) as call:
            with self.assertRaises(main.ModelConnectionError):
                main.model_reply('hello',[],self.config())
        call.assert_called_once()

    def test_connection_diagnostics_redact_secrets(self):
        m = {'api_key': 'secret-key', 'base_url': 'https://test.invalid/v1'}
        exc = main.URLError(OSError('DNS failed secret-key https://test.invalid/v1\nretry'))
        detail = main.connection_detail(exc, m)
        self.assertIn('DNS failed', detail)
        self.assertNotIn('secret-key', detail)
        self.assertNotIn('https://', detail)
        self.assertNotIn('\n', detail)

    def test_http_error_reports_status_only(self):
        exc = main.HTTPError('https://test.invalid', 429, 'secret response', {}, None)
        self.assertEqual(main.connection_detail(exc, {}), 'HTTP status=429')

    def test_429_body_and_retry_delay_are_reported_without_key(self):
        c = self.config()
        c['model']['api_key'] = 'secret-test-key'
        body = json.dumps({'code':20032, 'message':'RPM limit secret-test-key'}).encode()
        exc = main.HTTPError('https://model.invalid',429,'rate',{'Retry-After':'90'},io.BytesIO(body))
        with patch('main.urlopen', side_effect=exc) as call:
            with self.assertRaises(main.ModelRateLimitError) as caught:
                main.model_reply('hello',[],c)
        self.assertIn('RPM', str(caught.exception))
        self.assertNotIn('secret-test-key', str(caught.exception))
        self.assertEqual(caught.exception.retry_after, 90)
        self.assertFalse(caught.exception.daily_limit)
        call.assert_called_once()

    def test_daily_429_and_non_json_error_response(self):
        exc = main.HTTPError('https://model.invalid',429,'rate',{},io.BytesIO(b'{"error":{"message":"RPD limit"}}'))
        self.assertTrue(main.http_failure(exc, {}).daily_limit)
        exc = main.HTTPError('https://model.invalid',401,'auth',{},io.BytesIO(b'<html>secret key</html>'))
        error = main.http_failure(exc, {})
        self.assertEqual(str(error), 'HTTP status=401')
        self.assertFalse(error.retryable)

    def test_full_endpoint_and_style_profile_are_used_in_reply(self):
        c = self.config()
        c['model']['base_url']='https://test.invalid/v1/chat/completions'
        c['model']['style_profile']='短句，不使用长篇解释'
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'message':{'content':'好的'}}]}).encode()
        with patch('main.urlopen',return_value=response) as call:
            self.assertEqual(main.model_reply('hello',[],c),'好的')
        req=call.call_args.args[0]
        self.assertEqual(req.full_url,'https://test.invalid/v1/chat/completions')
        self.assertIn('短句，不使用长篇解释',json.loads(req.data)['messages'][0]['content'])


if __name__ == '__main__':
    unittest.main()
