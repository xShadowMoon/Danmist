import asyncio
import copy
import json
from unittest.mock import Mock, patch

import aiohttp
import moderation
import input_validation as valid
from test_backend import HubTest


class FakeContent:
    def __init__(self, body):
        self.body = body

    async def iter_chunked(self, size):
        for offset in range(0, len(self.body), size):
            yield self.body[offset:offset+size]


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self.content = FakeContent(payload if isinstance(payload, bytes) else json.dumps(payload).encode())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def row(number=1, **extra):
    return {'id': number, 'tuid': 1000+number, 'tname': '观众'+str(number), 'uid': 99, 'name': '房管',
            'ctime': '2026-01-01 12:00:00', 'face': '', 'type': 2, 'block_end_time': '', **extra}


def response(rows, total=None, pages=1, page=None):
    data = {'data': rows, 'total': len(rows) if total is None else total, 'total_page': pages}
    if page is not None:
        data['pn'] = page
    return FakeResponse({'code': 0, 'data': data})


class ModerationTests(HubTest):
    def setUp(self):
        super().setUp()
        self.state.room['bot_admin'] = True
        self.acct = {'cookie': 'SESSDATA=fake; bili_jct=fake-csrf; DedeUserID=99', 'uid': 99, 'uname': '测试房管'}
        self.hub.emit_admin = Mock()

    def service(self, *responses, demo=False):
        http = FakeHttp(*responses)
        service = moderation.MuteService(self.hub, http, 123, Mock(return_value=self.acct['cookie']), demo)
        return service, http

    def test_list_normal_empty_and_deadline_modes(self):
        async def check():
            service, http = self.service(response([row(), row(2, type=0), row(3, type=1, block_end_time='2026-12-01 12:00:00')]))
            ok, msg, data = await service.listing(moderation.MuteQuery(), self.acct)
            self.assertTrue(ok)
            items = data['mutes']['items']
            self.assertEqual([r['scope'] for r in items], ['session', 'permanent', 'timed'])
            self.assertEqual(items[0]['id'], '1')
            self.assertIsInstance(items[2]['until'], int)
            self.assertEqual(http.calls[0][1]['data']['pn'], '1')
            self.assertEqual(http.calls[0][1]['timeout'].total, 15)
            self.assertFalse(http.calls[0][1]['allow_redirects'])
            service, _ = self.service(response([], pages=0))
            self.assertEqual((await service.listing(moderation.MuteQuery()))[2]['mutes']['items'], [])
            unknown = row()
            unknown.pop('type')
            self.assertEqual(valid.mute_row(unknown)['scope'], 'unknown')
        asyncio.run(check())

    def test_bad_envelopes_and_partial_pages_fail_without_rows(self):
        async def check():
            for payload in ([], {'code': 10**50, 'data': {}}, b'['*1200 + b']'*1200, {'code': False, 'data': {}}, {'code': 1, 'data': {}}, {'code': 0},
                            {'code': 0, 'data': None}, {'code': 0, 'data': {'data': [], 'total': 1}}, b'not json', b'x'*(1024*1024+1)):
                with self.subTest(payload=str(payload)[:60]):
                    service, _ = self.service(FakeResponse(payload))
                    query = moderation.MuteQuery()
                    query.rows = [{'id': 'old'}]
                    ok, _, data = await service.listing(query)
                    self.assertFalse(ok)
                    self.assertEqual(data, {})
                    self.assertEqual(query.rows, [])
            service, _ = self.service(response([row()], 2, 2), FakeResponse({'code': -403, 'data': {}}))
            self.assertFalse((await service.listing(moderation.MuteQuery()))[0])
        asyncio.run(check())

    def test_invalid_rows_skipped_and_valid_fields_are_bounded(self):
        async def check():
            bad = [row(2, tuid=True), row(3, tname='字'*65), row(4, type=1, block_end_time='bad'),
                   row(5, face='javascript:bad'), row(6, id=[]), None]
            service, _ = self.service(response([row(), *bad]))
            ok, note, data = await service.listing(moderation.MuteQuery())
            self.assertTrue(ok)
            self.assertIn('跳过', note)
            self.assertEqual(len(data['mutes']['items']), 1)
            self.assertEqual(data['mutes']['skipped'], len(bad))
        asyncio.run(check())

    def test_pagination_cap_and_repeated_page_failure(self):
        async def check():
            pages = [response([row(i) for i in range(page*10+1, page*10+11)], 205, 21, page+1) for page in range(20)]
            service, http = self.service(*pages)
            ok, _, data = await service.listing(moderation.MuteQuery())
            self.assertTrue(ok)
            self.assertEqual(len(data['mutes']['items']), 200)
            self.assertTrue(data['mutes']['truncated'])
            self.assertEqual(len(http.calls), 20)
            service, _ = self.service(response([row()], 2, 2), response([row()], 2, 2))
            self.assertFalse((await service.listing(moderation.MuteQuery()))[0])
        asyncio.run(check())

    def test_no_permission_or_login_sends_no_request(self):
        async def check():
            service, http = self.service()
            self.state.room['bot_admin'] = False
            ok, note, _ = await service.listing(moderation.MuteQuery())
            self.assertFalse(ok)
            self.assertEqual(note, moderation.NO_ADMIN)
            service.cookie_reader.assert_not_called()
            self.assertFalse((await service.unmute(moderation.MuteQuery(), '1'))[0])
            ok, note, _ = await service.listing(moderation.MuteQuery(), {'cookie': '', 'uname': '小雾'})
            self.assertFalse(ok)
            self.assertIn('没登录', note)
            self.assertEqual(http.calls, [])
        asyncio.run(check())

    def test_list_rate_limit_is_per_connection_and_counts_failures(self):
        async def check():
            service, http = self.service(response([]), response([]), response([]))
            query = moderation.MuteQuery()
            with patch('moderation.time.monotonic', return_value=100):
                self.assertTrue((await service.listing(query))[0])
                self.assertFalse((await service.listing(query))[0])
                self.assertTrue((await service.listing(moderation.MuteQuery()))[0])
            with patch('moderation.time.monotonic', return_value=105):
                self.assertTrue((await service.listing(query))[0])
            self.assertEqual(len(http.calls), 3)
            service, http = self.service(FakeResponse({'code': -1}))
            query = moderation.MuteQuery()
            self.assertFalse((await service.listing(query))[0])
            self.assertFalse((await service.listing(query))[0])
            self.assertEqual(len(http.calls), 1)
        asyncio.run(check())

    def test_unmute_success_logs_actor_and_notifies_admins(self):
        async def check():
            service, http = self.service(response([row()]), FakeResponse({'code': 0, 'data': []}))
            query = moderation.MuteQuery()
            await service.listing(query, self.acct)
            with patch('moderation.log.info') as log:
                ok, note = await service.unmute(query, '1', self.acct)
            self.assertTrue(ok)
            self.assertEqual(http.calls[-1][0], moderation.UNMUTE_URL)
            self.assertEqual(http.calls[-1][1]['data']['roomid'], '123')
            self.assertEqual(http.calls[-1][1]['data']['id'], '1')
            self.assertNotIn('fake-csrf', str(log.call_args))
            self.assertIn('99', str(log.call_args))
            self.assertIn('1001', str(log.call_args))
            self.assertEqual(query.rows, [])
            self.assertEqual(self.hub.emit_admin.call_args.args[0], 'mutes')
        asyncio.run(check())

    def test_unmute_failure_or_timeout_never_retries_or_emits_success(self):
        async def check():
            for failed in (FakeResponse({'code': -403, 'data': []}), FakeResponse({'code': 0, 'data': None}),
                           FakeResponse({'code': 0, 'data': {'unexpected': 1}}), asyncio.TimeoutError(), aiohttp.ClientError()):
                service, http = self.service(response([row()]), failed)
                query = moderation.MuteQuery()
                await service.listing(query)
                self.assertFalse((await service.unmute(query, '1'))[0])
                self.assertEqual(len(http.calls), 2)
                self.assertEqual(len(query.rows), 1)
            self.hub.emit_admin.assert_not_called()
        asyncio.run(check())

    def test_switch_account_or_stale_list_requires_refresh(self):
        async def check():
            service, http = self.service(response([row()]))
            query = moderation.MuteQuery()
            await service.listing(query)
            other = {**self.acct, 'cookie': 'bili_jct=another; DedeUserID=2'}
            self.assertFalse((await service.unmute(query, '1', other))[0])
            query.fetched -= 301
            self.assertFalse((await service.unmute(query, '1'))[0])
            self.assertEqual(len(http.calls), 1)
        asyncio.run(check())

    def test_existing_mute_success_emits_refresh_and_keeps_session_scope(self):
        async def check():
            service, http = self.service(FakeResponse({'code': 0, 'data': {}}))
            ok, note = await service.mute(1001, '观众一', self.acct)
            self.assertTrue(ok)
            self.assertEqual(http.calls[0][1]['data']['type'], '2')
            self.assertEqual(http.calls[0][1]['data']['hour'], '0')
            self.assertEqual(self.hub.emit_admin.call_args.args[1]['action'], 'mute')
            service, _ = self.service(FakeResponse({'code': 0, 'data': {'id': 1}}))
            self.assertTrue((await service.mute(1001, '观众一', self.acct))[0])
        asyncio.run(check())

    def test_demo_uses_no_network_or_credentials(self):
        async def check():
            service, http = self.service(demo=True)
            service.cookie_reader = Mock(side_effect=AssertionError('不能读取登录凭据'))
            query = moderation.MuteQuery()
            ok, _, data = await service.listing(query)
            self.assertTrue(ok)
            item = data['mutes']['items'][0]
            self.assertTrue((await service.unmute(query, item['id']))[0])
            self.assertFalse((await service.unmute(query, item['id']))[0])
            self.assertEqual(len(service.demo_rows), 1)
            self.assertEqual(http.calls, [])
            service.cookie_reader.assert_not_called()
        asyncio.run(check())
