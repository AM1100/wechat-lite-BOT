from concurrent.futures import Future
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'wechat-desktop-bot'))
import unittest
from unittest.mock import MagicMock, patch
import main
import gui


class ManualExecutor:
    def __init__(self, immediate=False):
        self.jobs=[]
        self.immediate=immediate

    def submit(self, fn, text, context, config):
        future=Future()
        self.jobs.append((future,text,context))
        if self.immediate:
            future.set_result('回复 '+text)
        return future

    def shutdown(self, **kwargs):
        pass


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.c=main.read_config(Path(__file__).with_name('config.example.json'))
        self.c.update(enabled=True,dry_run=False,allowed_private_chats=['A','B','C'],model_concurrency=2)
        self.c['model'].update(base_url='https://test.invalid/v1',api_key='test-key',name='test-model')
        self.store=main.Store(':memory:')
        self.addCleanup(self.store.db.close)
        self.executor=ManualExecutor()
        self.queue=main.ReplyQueue(self.store,self.executor)
        self.queue.reset(main.signature(self.c))

    def test_three_simultaneous_messages_queue_third_while_two_models_wait(self):
        for name in ('A','B','C'):
            self.queue.receive(name,['消息'+name],100,self.c)
        self.queue.launch(self.c,110)
        self.assertEqual(set(self.queue.active),{'A','B'})
        self.assertEqual(set(self.queue.pending),{'C'})
        self.queue.receive('C',['补充'],111,self.c)
        self.executor.jobs[0][0].set_result('回复A')
        self.queue.harvest()
        self.queue.launch(self.c,120)
        self.assertEqual(set(self.queue.active),{'B','C'})
        self.assertEqual(self.queue.ready['A']['reply'],'回复A')
        self.assertEqual(self.executor.jobs[2][1],'消息C\n补充')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM calls').fetchone()[0],3)

    def test_global_spacing_applies_across_friends_without_charging_wait(self):
        self.c['global_request_interval_seconds'] = 10
        for name in ('A','B','C'):
            self.queue.receive(name,[name],100,self.c)
        self.queue.launch(self.c,110)
        self.queue.launch(self.c,119)
        self.assertEqual(len(self.executor.jobs),1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM calls').fetchone()[0],1)
        self.queue.launch(self.c,120)
        self.assertEqual(len(self.executor.jobs),2)

    def test_delayed_send_confirmation_preserves_later_messages_and_records_once(self):
        self.queue.receive('A',['first'],100,self.c)
        self.queue.launch(self.c,110)
        self.executor.jobs[0][0].set_result('reply')
        self.queue.harvest()
        job = self.queue.ready['A']
        self.queue.await_confirmation('A',job,[('in','first')],111)
        self.queue.receive('A',['later'],112,self.c)
        self.queue.receive('B',['other'],112,self.c)
        self.queue.launch(self.c,120)
        self.assertIn('B', self.queue.active)
        self.assertNotIn('A', self.queue.active)
        self.assertEqual(len(self.executor.jobs),2)
        snap = {'name':'A','draft':'','rows':[('in','first'),('out','reply'),('in','later')]}
        self.assertEqual(self.queue.confirm_snapshot(snap),'reply')
        self.assertIsNone(self.queue.confirm_snapshot(snap))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM history').fetchone()[0],1)
        self.queue.launch(self.c,121)
        self.assertEqual(self.executor.jobs[-1][1], 'later')
        self.assertEqual(self.executor.jobs[-1][2][-1]['content'], 'reply')

    def test_unconfirmed_send_expires_without_resend_or_duplicate_api_call(self):
        self.queue.receive('A',['first'],100,self.c)
        self.queue.launch(self.c,110)
        self.executor.jobs[0][0].set_result('reply')
        self.queue.harvest()
        self.queue.await_confirmation('A',self.queue.ready['A'],[('in','first')],111)
        self.queue.expire_confirmations(142)
        self.queue.launch(self.c,150)
        self.assertEqual(len(self.executor.jobs),1)
        self.assertFalse(self.queue.ready)
        self.assertFalse(self.queue.confirming)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM history').fetchone()[0],0)

    def test_429_pauses_all_friends_and_retries_only_once(self):
        self.queue.receive('A',['first'],100,self.c)
        self.queue.launch(self.c,110)
        self.executor.jobs[0][0].set_exception(main.ModelRateLimitError('RPM limit', 90))
        with patch('main.time.time',return_value=111):
            self.queue.harvest()
        self.queue.receive('B',['other'],112,self.c)
        self.queue.launch(self.c,200)
        self.assertEqual(len(self.executor.jobs),1)
        self.assertIn('B',self.queue.pending)
        self.queue.launch(self.c,201)
        self.assertEqual(len(self.executor.jobs),3)
        self.executor.jobs[1][0].set_exception(main.ModelRateLimitError('RPM limit'))
        self.executor.jobs[2][0].set_result('B reply')
        with patch('main.time.time',return_value=202):
            self.queue.harvest()
        self.queue.launch(self.c,400)
        self.assertEqual(len(self.executor.jobs),3)
        self.assertNotIn('A',self.queue.retry)
        self.assertEqual(self.queue.ready['B']['reply'], 'B reply')

    def test_daily_limit_blocks_new_requests_until_next_day(self):
        self.queue.receive('A',['first'],100,self.c)
        self.queue.launch(self.c,110)
        self.executor.jobs[0][0].set_exception(main.ModelRateLimitError('RPD limit',daily_limit=True))
        with patch('main.time.time',return_value=111):
            self.queue.harvest()
        self.queue.receive('B',['other'],112,self.c)
        self.queue.launch(self.c,500)
        self.assertEqual(len(self.executor.jobs),1)
        self.assertNotIn('A',self.queue.retry)
        self.queue.receive('C',['next day'],86500,self.c)
        self.queue.launch(self.c,86510)
        self.assertEqual(len(self.executor.jobs),2)
        self.assertIn('C',self.queue.active)

    def test_one_model_failure_keeps_other_friends(self):
        for name in ('A','B','C'):
            self.queue.receive(name,[name],100,self.c)
        self.queue.launch(self.c,110)
        self.executor.jobs[0][0].set_exception(ValueError('empty response'))
        self.executor.jobs[1][0].set_result('B回复')
        self.queue.harvest()
        self.queue.launch(self.c,120)
        self.assertNotIn('A',self.queue.active)
        self.assertEqual(self.queue.ready['B']['reply'],'B回复')
        self.assertIn('C',self.queue.active)
        self.assertEqual(len(self.executor.jobs),3)

    def test_timeout_retries_once_preserves_context_and_later_messages(self):
        self.queue.receive('A',['first'],100,self.c)
        self.queue.launch(self.c,110)
        self.executor.jobs[0][0].set_exception(main.ModelConnectionError('timeout', True))
        with patch('main.time.time', return_value=111):
            self.queue.harvest()
        self.queue.receive('A',['later'],112,self.c)
        self.queue.receive('B',['other'],112,self.c)
        self.queue.launch(self.c,118)
        self.assertIn('B',self.queue.active)
        self.assertIn('A',self.queue.retry)
        self.queue.launch(self.c,121)
        self.assertEqual(self.executor.jobs[-1][1], 'first')
        self.assertEqual(self.executor.jobs[-1][2], self.executor.jobs[0][2])
        self.executor.jobs[-1][0].set_result('reply')
        self.queue.harvest()
        self.assertEqual(self.queue.ready['A']['reply'], 'reply')
        self.assertEqual(self.queue.pending['A']['texts'], ['later'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM calls').fetchone()[0],3)

    def test_second_timeout_stops_and_budget_is_respected(self):
        self.queue.receive('A',['first'],100,self.c)
        self.queue.launch(self.c,110)
        self.executor.jobs[0][0].set_exception(TimeoutError())
        with patch('main.time.time', return_value=111):
            self.queue.harvest()
        self.c['max_requests_per_day'] = 1
        self.queue.launch(self.c,121)
        self.assertEqual(len(self.executor.jobs),1)
        self.c['max_requests_per_day'] = 60
        self.queue.launch(self.c,122)
        self.executor.jobs[1][0].set_exception(TimeoutError())
        self.queue.harvest()
        self.queue.launch(self.c,140)
        self.assertEqual(len(self.executor.jobs),2)
        self.assertFalse(self.queue.retry)
        self.assertFalse(self.queue.ready)

    def test_manual_cancel_and_config_reset_remove_scheduled_retry(self):
        for index, method in enumerate(('cancel', 'reset')):
            clock = 200 + index*100
            self.queue.receive('A',['first'],clock,self.c)
            self.queue.launch(self.c,clock+20)
            self.executor.jobs[-1][0].set_exception(TimeoutError())
            with patch('main.time.time', return_value=clock+21):
                self.queue.harvest()
            self.assertIn('A',self.queue.retry)
            if method == 'cancel':
                self.queue.cancel('A')
            else:
                self.queue.reset('new-signature')
            self.queue.launch(self.c,clock+40)
            self.assertFalse(self.queue.retry)
            self.assertFalse(self.queue.active)

    def test_cooldown_retains_messages_without_charging_extra_attempt(self):
        self.store.reserve('A',self.c,100)
        self.queue.receive('A',['等冷却'],101,self.c)
        self.queue.launch(self.c,106)
        self.assertIn('A',self.queue.pending)
        self.assertEqual(len(self.executor.jobs),0)
        self.queue.launch(self.c,111)
        self.assertEqual(len(self.executor.jobs),1)

    def test_manual_reply_cancels_only_one_friend(self):
        for name in ('A','B','C'):
            self.queue.receive(name,[name],100,self.c)
        self.queue.launch(self.c,110)
        self.queue.cancel('A')
        self.executor.jobs[0][0].set_result('旧A回复')
        self.executor.jobs[1][0].set_result('B回复')
        self.queue.harvest()
        self.assertNotIn('A',self.queue.ready)
        self.assertIn('B',self.queue.ready)
        self.assertIn('C',self.queue.pending)

    def test_new_messages_for_same_friend_wait_for_previous_reply(self):
        self.queue.receive('A',['第一条'],100,self.c)
        self.queue.launch(self.c,110)
        self.queue.receive('A',['第二条'],111,self.c)
        self.queue.launch(self.c,120)
        self.assertEqual(len(self.executor.jobs),1)
        self.executor.jobs[0][0].set_result('第一条回复')
        self.queue.harvest()
        self.queue.launch(self.c,130)
        self.assertEqual(len(self.executor.jobs),1)
        job=self.queue.ready.pop('A')
        self.store.record('A',job['text'],job['reply'])
        self.queue.launch(self.c,140)
        self.assertEqual(len(self.executor.jobs),2)
        self.assertEqual(self.executor.jobs[1][1],'第二条')
        self.assertEqual(self.executor.jobs[1][2][-1]['content'],'第一条回复')

    def test_changed_config_never_sends_old_result(self):
        self.queue.receive('A',['旧配置'],100,self.c)
        self.queue.launch(self.c,110)
        self.queue.reset('new-signature')
        self.executor.jobs[0][0].set_result('旧模型回复')
        self.queue.harvest()
        self.assertEqual(self.queue.ready,{})

    def test_main_loop_three_recipients_and_missing_friend_does_not_reset_all(self):
        clock={'now':100,'ticks':0}
        class FakeGui:
            def __init__(self):
                self.name='A'
                self.rows={n:[('ignore','开始')] for n in ('A','B','C')}
                self.sent=[]
                self.failed=False
                self.deferrals=0
            def scan(self):
                if clock['ticks']==5:
                    for n in self.rows:
                        item=('in','消息'+n)
                        if item not in self.rows[n]:
                            if n == 'B':
                                self.rows[n].append(('unknown','unrecognized bubble'))
                            self.rows[n].append(item)
                            if n == 'A':
                                self.rows[n].extend([('in','补充1'),('in','补充2')])
                return {'name':self.name,'rows':list(self.rows[self.name]),'draft':'','targets':{}}
            def select(self,name,snap):
                if name=='B' and clock['ticks']==7 and not self.failed:
                    self.failed=True
                    raise RuntimeError('temporarily missing friend B')
                self.name=name
                return self.scan()
            def send_reply(self,name,text,rows,allowed):
                assert allowed()
                assert self.name==name
                if name=='A' and self.deferrals==0:
                    self.deferrals+=1
                    raise gui.SendDeferred('new message before send; no click occurred')
                self.rows[name].append(('out',text))
                self.sent.append(name)
                return self.scan()
            def close(self):pass
        fake=FakeGui()
        executor=ManualExecutor(immediate=True)
        self.c['rotate_visible_chats']=True
        def tick(seconds):
            clock['ticks']+=1
            clock['now']+=seconds
            if clock['ticks']>=45:raise KeyboardInterrupt()
        with patch('gui.Gui',return_value=fake), patch('main.ThreadPoolExecutor',return_value=executor), \
             patch('main.read_config',return_value=self.c), patch('main.write_runtime'), \
             patch('main.time.time',side_effect=lambda:clock['now']), patch('main.time.sleep',side_effect=tick):
            with self.assertRaises(KeyboardInterrupt):
                main.run('fake-config',self.store)
        self.assertTrue(fake.failed)
        self.assertEqual(fake.deferrals,1)
        self.assertCountEqual(fake.sent,['A','B','C'])
        self.assertEqual(len(executor.jobs),3)
        self.assertIn('消息A\n补充1\n补充2', [job[1] for job in executor.jobs])

    def test_viewport_overlap_loss_does_not_discard_ready_reply(self):
        clock={'now':100,'ticks':0}
        class FakeGui:
            def __init__(self):
                self.rows=[('in','old')]
                self.sent=0
                self.shifted=False
            def scan(self):
                if clock['ticks']==2 and self.rows == [('in','old')]:
                    self.rows.append(('in','new'))
                if executor.jobs and not self.shifted:
                    self.shifted=True
                    self.rows=[('in','different visible viewport')]
                return {'name':'A','rows':list(self.rows),'draft':'','targets':{}}
            def send_reply(self,name,text,rows,allowed):
                self.sent+=1
                self.rows.append(('out',text))
                return self.scan()
            def close(self):pass
        executor=ManualExecutor(immediate=True)
        fake=FakeGui()
        self.c.update(rotate_visible_chats=False, allowed_private_chats=['A'])
        def tick(seconds):
            clock['ticks']+=1
            clock['now']+=seconds
            if clock['ticks']>=15:raise KeyboardInterrupt()
        with patch('gui.Gui',return_value=fake), patch('main.ThreadPoolExecutor',return_value=executor), \
             patch('main.read_config',return_value=self.c), patch('main.write_runtime'), \
             patch('main.time.time',side_effect=lambda:clock['now']), patch('main.time.sleep',side_effect=tick):
            with self.assertRaises(KeyboardInterrupt):
                main.run('fake-config',self.store)
        self.assertTrue(fake.shifted)
        self.assertEqual(fake.sent,1)
        self.assertEqual(len(executor.jobs),1)


if __name__=='__main__':unittest.main()
