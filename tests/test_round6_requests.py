"""回复弹幕与公告：断言请求字段、重试次数和演示模式入口。"""
import asyncio
from unittest.mock import patch

import server
import input_validation as valid
from round6_helpers import RoundSixTest, Http, Reply, run_without_io


class ReplyTests(RoundSixTest):
    def setUp(self):
        super().setUp()
        self.state.room = {'room_real': 456, 'uid': 7}
        self.acct = {'uid': 7, 'uname': '假账号', 'cookie': 'bili_jct=fake-csrf; SESSDATA=fake'}
        self.at = {}

    def send(self, http, text='你好', uid=8, dmid='abc123', acct=None):
        return run_without_io(server.send_own_danmaku(http, self.state, 123, self.at,
                                                     self.acct if acct is None else acct, text, uid, dmid))

    def test_command_with_and_without_reply_valid(self):
        for extra in ({}, {'reply_uid': 8, 'reply_dmid': 'a' * 64}, {'reply_uid': 0, 'reply_dmid': ''}):
            valid.validate_command({'cmd': 'say', 'text': '你好', **extra}, server.clean_rules)

    def test_command_rejects_bad_reply_fields(self):
        for extra in ({'reply_uid': -1}, {'reply_uid': True}, {'reply_uid': '8'}, {'reply_uid': 10**20},
                      {'reply_dmid': 'a' * 65}, {'reply_dmid': 'bad-id'}, {'reply_dmid': 9}):
            with self.subTest(extra=extra), self.assertRaises(valid.InputError):
                valid.validate_command({'cmd': 'say', 'text': '你好', **extra}, server.clean_rules)

    def test_reply_form_and_real_room(self):
        http = Http(Reply({'code': 0}))
        ok, note = self.send(http)
        self.assertTrue(ok)
        self.assertIn('回复', note)
        form = http.calls[0][2]['data']
        self.assertEqual((form['reply_mid'], form['replay_dmid'], form['roomid']), ('8', 'abc123', '456'))
        self.assertEqual((form['csrf'], form['csrf_token']), ('fake-csrf', 'fake-csrf'))
        self.assertEqual(len(http.calls), 1)

    def test_no_reply_uses_neutral_fields(self):
        http = Http(Reply({'code': 0}))
        self.assertTrue(self.send(http, uid=0, dmid='')[0])
        self.assertEqual((http.calls[0][2]['data']['reply_mid'], http.calls[0][2]['data']['replay_dmid']), ('0', ''))

    def test_rejected_reply_retries_once_without_reply_target(self):
        http = Http(Reply({'code': -400, 'message': '拒绝回复'}), Reply({'code': 0}))
        ok, note = self.send(http)
        self.assertTrue(ok)
        self.assertIn('按普通弹幕发出了', note)
        first, second = [c[2]['data'] for c in http.calls]
        self.assertEqual((first['reply_mid'], first['replay_dmid']), ('8', 'abc123'))
        # 现有实现用 0 和空串取消回复，仍保留字段；不能擅自改表单格式。
        self.assertEqual(second, {**first, 'reply_mid': '0', 'replay_dmid': ''})

    def test_expired_login_never_retries(self):
        http = Http(Reply({'code': -101}))
        ok, note = self.send(http)
        self.assertFalse(ok)
        self.assertIn('登录过期', note)
        self.assertEqual(len(http.calls), 1)

    def test_second_failure_has_no_third_request(self):
        http = Http(Reply({'code': -400}), Reply({'code': -400}))
        self.assertFalse(self.send(http)[0])
        self.assertEqual(len(http.calls), 2)

    def test_nonreply_failure_not_retried(self):
        http = Http(Reply({'code': -400}))
        self.assertFalse(self.send(http, uid=0, dmid='')[0])
        self.assertEqual(len(http.calls), 1)

    def test_network_failure_not_retried(self):
        for error in (server.aiohttp.ClientError('假断网'), asyncio.TimeoutError()):
            with self.subTest(error=type(error).__name__):
                self.at.clear()
                http = Http(Reply(error=error))
                self.assertEqual(self.send(http), (False, '连不上 B 站，稍后再试'))
                self.assertEqual(len(http.calls), 1)

    def test_invalid_text_and_missing_csrf_do_not_send(self):
        http = Http()
        for text in ('', '  ', '字' * 41):
            self.assertFalse(self.send(http, text=text)[0])
        self.assertFalse(self.send(http, acct={'uid': 7, 'cookie': ''})[0])
        self.assertEqual(http.calls, [])

    def test_per_account_rate_limit(self):
        http = Http(Reply({'code': 0}))
        with patch.object(server.time, 'time', return_value=100):
            self.assertTrue(self.send(http)[0])
            self.assertFalse(self.send(http)[0])
        self.assertEqual(len(http.calls), 1)


class NewsTests(RoundSixTest):
    def setUp(self):
        super().setUp()
        self.state.room = {'room_real': 456, 'uid': 7}
        self.acct = {'uid': 7, 'uname': '假主播', 'cookie': 'bili_jct=fake-csrf'}

    def get(self, http):
        return run_without_io(server.get_room_news(http, self.state, 123))

    def set(self, http, text='新公告', acct=None):
        return run_without_io(server.set_room_news(http, self.state, 123, self.acct if acct is None else acct, text))

    def test_get_news_content_and_params(self):
        http = Http(Reply({'code': 0, 'data': {'content': '公告', 'ctime': '2026-11-21'}}))
        self.assertEqual(self.get(http), (True, '', {'text': '公告', 'ctime': '2026-11-21'}))
        self.assertEqual(http.calls[0][2]['params'], {'roomid': '456', 'uid': '7'})

    def test_get_error_response(self):
        self.assertFalse(self.get(Http(Reply({'code': -400, 'message': '拒绝'})))[0])

    def test_get_connection_timeout_and_bad_json(self):
        for error in (server.aiohttp.ClientError(), asyncio.TimeoutError(), ValueError()):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(self.get(Http(Reply(error=error))), (False, '连不上 B 站，稍后再试', {}))

    def test_get_missing_room_uid_does_not_request(self):
        self.state.room = {}
        http = Http()
        self.assertFalse(self.get(http)[0])
        self.assertEqual(http.calls, [])

    def test_get_empty_and_bounded_data(self):
        self.assertEqual(self.get(Http(Reply({'code': 0, 'data': None})))[2], {'text': '', 'ctime': ''})
        data = self.get(Http(Reply({'code': 0, 'data': {'content': '字' * 201, 'ctime': 'x' * 21}})))[2]
        self.assertEqual((len(data['text']), len(data['ctime'])), (200, 20))

    def test_set_requires_anchor_account(self):
        http = Http()
        for acct in ({}, {**self.acct, 'uid': 8}):
            self.assertFalse(self.set(http, acct=acct)[0])
        self.assertEqual(http.calls, [])

    def test_set_requires_csrf(self):
        http = Http()
        self.assertFalse(self.set(http, acct={**self.acct, 'cookie': ''})[0])
        self.assertEqual(http.calls, [])

    def test_set_over_sixty_rejected(self):
        http = Http()
        self.assertFalse(self.set(http, text='字' * 61)[0])
        with self.assertRaises(valid.InputError):
            valid.validate_command({'cmd': 'news_set', 'acct': 'a' * 32, 'text': '字' * 61}, server.clean_rules)
        self.assertEqual(http.calls, [])

    def test_set_sixty_accepted_and_read_back(self):
        text = '字' * 60
        http = Http(Reply({'code': 0}), Reply({'code': 0, 'data': {'content': text}}))
        self.assertEqual(self.set(http, text), (True, '公告改好了'))
        self.assertTrue(http.calls[0][1].endswith('/xlive/app-blink/v1/index/updateRoomNews'))
        self.assertEqual(http.calls[0][2]['data'], {'room_id': '456', 'uid': '7', 'content': text,
                                                   'csrf': 'fake-csrf', 'csrf_token': 'fake-csrf'})
        self.assertEqual([c[0] for c in http.calls], ['POST', 'GET'])

    def test_set_http_404_falls_back_to_second_endpoint(self):
        http = Http(Reply(status=404), Reply({'code': 0}), Reply({'code': 0, 'data': {'content': '新公告'}}))
        self.assertEqual(self.set(http), (True, '公告改好了'))
        self.assertTrue(http.calls[1][1].endswith('/room_ex/v1/RoomNews/update'))
        form = http.calls[1][2]['data']
        self.assertEqual(form['roomid'], '456')
        self.assertNotIn('room_id', form)
        self.assertEqual([c[0] for c in http.calls], ['POST', 'POST', 'GET'])

    def test_set_existing_fallback_codes(self):
        for code in (-404, -400, 404):
            with self.subTest(code=code):
                http = Http(Reply({'code': code}), Reply({'code': -999}))
                self.assertFalse(self.set(http)[0])
                self.assertEqual(len(http.calls), 2)

    def test_set_other_error_and_login_expiry_do_not_fallback(self):
        for code in (-101, -403, -999):
            with self.subTest(code=code):
                http = Http(Reply({'code': code}))
                self.assertFalse(self.set(http)[0])
                self.assertEqual(len(http.calls), 1)

    def test_set_network_failure_does_not_retry(self):
        http = Http(Reply(error=asyncio.TimeoutError()))
        self.assertFalse(self.set(http)[0])
        self.assertEqual(len(http.calls), 1)

    def test_set_success_old_or_unreadable_content_is_honest(self):
        for reply in (Reply({'code': 0, 'data': {'content': '旧公告'}}), Reply(error=asyncio.TimeoutError())):
            http = Http(Reply({'code': 0}), reply)
            ok, note = self.set(http)
            self.assertTrue(ok)
            self.assertIn('可能要审核', note)


class DemoCommandTests(RoundSixTest):
    def test_demo_say_and_news_set_never_send(self):
        self.bootstrap()
        ws = self.websocket([{'cmd': 'say', 'text': '你好', 'reply_uid': 8, 'reply_dmid': 'abc'},
                             {'cmd': 'news_set', 'acct': 'a' * 32, 'text': '公告'}])
        results = [r['data'] for r in ws.sent if r['type'] == 'result']
        self.assertEqual(len(results), 2)
        self.assertTrue(all(not r['ok'] and '演示模式' in r['msg'] for r in results))
        self.assertEqual(self.bare.calls + self.session.calls, [])
        self.assertTrue(ws.closed)


class BotCommandTests(RoundSixTest):
    def test_bot_say_does_not_forward_reply_fields(self):
        self.bootstrap(demo=False)
        (self.root / 'bot.token').write_text('fake-local-token', encoding='utf-8')
        self.session.replies = [Reply({'ok': True})]
        ws = self.websocket([{'cmd': 'say', 'text': '你好', 'reply_uid': 8, 'reply_dmid': 'abc'}])
        result = next(r['data'] for r in ws.sent if r['type'] == 'result')
        self.assertTrue(result['ok'])
        self.assertEqual(len(self.session.calls), 1)
        method, url, options = self.session.calls[0]
        self.assertEqual((method, url), ('POST', 'http://127.0.0.1:18771/api/danmu/say'))
        self.assertEqual(options['json'], {'text': '你好', 'from': '直播姬'})
        self.assertEqual(options['headers']['X-Local-Token'], 'fake-local-token')

    def test_own_account_websocket_passes_reply_to_sender(self):
        self.bootstrap(demo=False)
        acct = {'uid': 7, 'uname': '假账号', 'cookie': 'bili_jct=fake'}
        with patch.object(server.Accounts, 'get', return_value=acct), \
                patch.object(server, 'send_own_danmaku', return_value=(True, '已回复')) as send:
            ws = self.websocket([{'cmd': 'say', 'text': '你好', 'acct': 'a' * 32,
                                  'reply_uid': 8, 'reply_dmid': 'abc'}])
        self.assertEqual(send.call_args.args[-4:], (acct, '你好', 8, 'abc'))
        self.assertTrue(next(r['data'] for r in ws.sent if r['type'] == 'result')['ok'])
        self.assertEqual(self.session.calls + self.bare.calls, [])
