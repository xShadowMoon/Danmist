"""切房内存隔离、只读命令、连接回收与历史弹幕，全部用假连接。"""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import server
import input_validation as valid
from round6_helpers import RoundSixTest, Http, Reply, Ws, run_without_io


class SideStateTests(RoundSixTest):
    def test_memstate_never_reads_or_writes_existing_room_file(self):
        p = self.root / 'data' / '456.json'
        server.write_json(str(p), {'songs': [{'id': 's', 'name': '不能读到', 'done': False}]})
        before = p.read_bytes()
        with patch('builtins.open', side_effect=AssertionError('不能读写文件')), \
                patch.object(server, 'write_json', side_effect=AssertionError('不能保存')):
            state = server.MemState(456)
            self.assertEqual(state.songs, [])
            state.dirty = True
            state.save()
        self.assertEqual(p.read_bytes(), before)

    def test_side_lifecycle_and_history_never_persist(self):
        history = server.NullHistory()
        with patch('builtins.open', side_effect=AssertionError('不能读写文件')), \
                patch.object(server, 'write_json', side_effect=AssertionError('不能保存')):
            h = server.SideHub(server.MemState(456), history, persist=False)
            before = copy.deepcopy(h.state.snapshot())
            h.settle('下播')
            h.close_broadcast('下播')
            h.save_offline()
            h.new_session('手动清零')
            h.state.save()
            history.save({'id': 'x'})
            self.assertEqual(h.state.snapshot(), before)
            self.assertEqual(history.list(), [])
            self.assertIsNone(history.get('x'))
            self.assertFalse(history.has_dm('x'))

    def test_events_and_websocket_pushes_are_isolated_both_ways(self):
        side = server.SideHub(server.MemState(456), server.NullHistory(), persist=False)
        main_ws, side_ws = Ws(), Ws()
        self.hub.sockets[main_ws] = True
        side.sockets[side_ws] = True

        async def immediate_wait(coro, timeout):
            return await coro

        async def immediate_gather(*coros):
            return [await coro for coro in coros]

        self.hub.emit = server.Hub.emit.__get__(self.hub)
        loop = SimpleNamespace(create_task=lambda coro: run_without_io(coro))
        with patch.object(server.asyncio, 'get_event_loop', return_value=loop), \
                patch.object(server.asyncio, 'wait_for', side_effect=immediate_wait), \
                patch.object(server.asyncio, 'gather', side_effect=immediate_gather):
            side.danmaku(7, '侧房观众', '', '侧房弹幕')
            self.assertEqual(main_ws.sent, [])
            self.assertEqual(self.state.dm, [])
            server.Hub.emit(self.hub, 'room', {'title': '主房'})
            self.hub.danmaku(8, '主房观众', '', '主房弹幕')
        self.assertEqual([m['type'] for m in side_ws.sent], ['dm'])
        self.assertEqual(main_ws.sent[0]['data']['title'], '主房')
        self.assertEqual(main_ws.sent[1]['data']['text'], '主房弹幕')
        self.assertEqual(side.state.dm[0]['text'], '侧房弹幕')
        self.assertEqual(len(side.state.dm), 1)


class BackfillTests(RoundSixTest):
    def fill(self, rows):
        http = Http(Reply({'data': {'room': rows}}))
        run_without_io(server.backfill_side_room(http, self.hub, 456))
        return http

    def test_normal_row_original_timestamp_and_dmid(self):
        http = self.fill([{'uid': 7, 'nickname': '观众', 'text': '旧弹幕', 'timeline': '2026-11-20 23:59:00', 'id_str': 'abc123'}])
        row = self.state.dm[0]
        self.assertEqual((row['uid'], row['text'], row['dmid']), (7, '旧弹幕', 'abc123'))
        self.assertEqual(row['t'], int(server.live_ts('2026-11-20 23:59:00')))
        self.assertEqual(http.calls[0][2]['params']['roomid'], '456')

    def test_nested_user_and_medal_fields(self):
        self.fill([{'user': {'uid': 7, 'base': {'name': '观众'}, 'medal': {'name': '粉丝牌', 'level': 3}},
                    'text': '你好', 'medal': []}])
        self.assertEqual((self.state.dm[0]['uid'], self.state.dm[0]['medal'], self.state.dm[0]['medal_level']), (7, '粉丝牌', 3))

    def test_missing_fields_and_non_dict_rows_do_not_crash(self):
        self.fill([None, 42, 'bad', {}, {'text': '只有文字'}])
        self.assertEqual([r['text'] for r in self.state.dm], ['', '只有文字'])

    def test_empty_or_non_dict_response(self):
        for payload in ({}, {'data': {}}, {'data': {'room': []}}, []):
            run_without_io(server.backfill_side_room(Http(Reply(payload)), self.hub, 456))
        self.assertEqual(self.state.dm, [])

    def test_only_last_ten_rows(self):
        self.fill([{'uid': 7, 'nickname': '观众', 'text': str(i)} for i in range(12)])
        self.assertEqual([r['text'] for r in self.state.dm], [str(i) for i in range(2, 12)])

    def test_connection_error_returns_without_rows(self):
        run_without_io(server.backfill_side_room(Http(Reply(error=asyncio.TimeoutError())), self.hub, 456))
        self.assertEqual(self.state.dm, [])

    def test_bad_numeric_row_is_skipped(self):
        # 2026-11-21 补上：数字字段不是数字的那一条跳过，同一批里正常的照样补
        for bad in ({'uid': 'bad'}, {'medal': ['bad']}, {'guard_level': 'bad'}):
            with self.subTest(row=bad):
                self.state.dm.clear()
                self.fill([{'text': '坏', **bad}, {'uid': 7, 'nickname': '观众', 'text': '好'}])
                self.assertEqual([d['text'] for d in self.state.dm], ['好'])


class SideGcTests(RoundSixTest):
    def entry(self):
        return {'hub': SimpleNamespace(sockets={}, side_info={'room': 456}),
                'client': SimpleNamespace(stop_and_close=AsyncMock()), 'task': Mock(), 'idle': 0}

    def cycles(self, entries, count, before=None):
        calls = 0

        async def sleep(seconds):
            nonlocal calls
            self.assertEqual(seconds, 60)
            if before:
                before(calls)
            if calls == count:
                raise asyncio.CancelledError()
            calls += 1

        with patch.object(server.asyncio, 'sleep', side_effect=sleep):
            with self.assertRaises(asyncio.CancelledError):
                run_without_io(server.collect_side_rooms(entries))

    def test_unused_connection_closes_after_two_cycles(self):
        e = self.entry()
        entries = {456: e}
        def before(n):
            if n == 1:
                self.assertEqual(e['idle'], 1)
                e['client'].stop_and_close.assert_not_called()
        self.cycles(entries, 2, before)
        self.assertEqual(entries, {})
        e['client'].stop_and_close.assert_awaited_once()
        e['task'].cancel.assert_called_once()

    def test_viewer_resets_idle_counter(self):
        e = self.entry()
        e['idle'] = 1
        e['hub'].sockets[object()] = True
        entries = {456: e}
        self.cycles(entries, 2)
        self.assertEqual(e['idle'], 0)
        e['client'].stop_and_close.assert_not_called()
        self.assertIn(456, entries)

    def test_failed_close_does_not_leave_cached_connection(self):
        e = self.entry()
        e['client'].stop_and_close.side_effect = OSError('假关连接失败')
        entries = {456: e}
        self.cycles(entries, 2)
        self.assertEqual(entries, {})

    def test_aliases_count_once_per_cycle(self):
        # 2026-11-21 补上：短房号和真房号指向同一套，每轮只数一次，第二轮才关
        e = self.entry()
        entries = {12: e, 456: e}
        self.cycles(entries, 1)
        self.assertEqual(set(entries), {12, 456})
        self.assertEqual(e['idle'], 1)
        e['client'].stop_and_close.assert_not_awaited()
        self.cycles(entries, 1)
        self.assertEqual(entries, {})
        e['client'].stop_and_close.assert_awaited_once()


class SideWebsocketTests(RoundSixTest):
    def setUp(self):
        super().setUp()
        self.bootstrap()
        self.client = Mock()
        self.client.stop_and_close = AsyncMock()
        self.enterContext(patch.object(server.blivedm, 'BLiveClient', return_value=self.client))
        self.session.replies = [Reply({'data': {'uid': 99, 'room_id': 456}}),
                                Reply({'data': {'info': {'uname': '侧房主播'}}}), Reply({'data': {'room': []}})]

    def test_all_valid_commands_rejected_on_side_room(self):
        token = 'a' * 32
        overrides = {
            'unmute': {'id': '1'}, 'gift_thank': {'id': 'g', 'done': True}, 'sc_read': {'id': '1', 'read': True},
            'admin_link_revoke': {'id': token}, 'admin_link_open_del': {'id': token, 't': 1},
            'profile_get': {'name': '方案'}, 'profile_delete': {'name': '方案'},
            'profile_save': {'name': '方案', 'content': {'v': 5}},
            'song_add': {'text': '歌'}, 'song_done': {'id': 's'}, 'song_del': {'id': 's'},
            'song_now': {'id': 's'}, 'song_move': {'id': 's', 'before': ''},
            'library_save': {'song': {'name': '歌'}}, 'library_import': {'rows': [{'name': '歌'}]},
            'library_delete': {'name': '歌'}, 'req_rules': {'max': 3},
            'req_done': {'id': 'r'}, 'req_del': {'id': 'r'}, 'req_clear': {'kind': 'song'},
            'note_set': {'uid': 7, 'text': '备注'}, 'say': {'text': '你好'}, 'mute': {'uid': 7},
            'news_set': {'acct': token, 'text': '公告'}, 'room_edit': {'acct': token, 'title': '标题'},
            'acct_poll': {'key': 'fake'}, 'acct_info': {'acct': token}, 'acct_logout': {'acct': token}, 'acct_connect': {'acct': token},
            'tpre_set': {'list': []}, 'live_start': {'acct': token}, 'live_stop': {'acct': token},
            'lan_set': {'on': True}, 'open_mode': {'mode': 'app'}, 'music_cookie': {'src': '163', 'cookie': 'MUSIC_U=x'},
            'music_del': {'id': 'm'}, 'music_logout': {'src': '163'}, 'music_ok': {'id': 'm'}, 'music_poll': {'src': '163', 'key': 'k'},
            'music_qr': {'src': '163'}, 'music_top': {'id': 'm'}, 'music_vol': {'vol': 50}, 'music_add': {'text': 'x'}, 'music_alts': {'id': 'm'}, 'music_swap': {'id': 'm', 'sid': '1'}, 'music_weblogin': {'src': '163'}, 'music_move': {'id': 'm'}, 'plat_set': {'rooms': []}, 'plat_show': {'plat': 'douyin', 'room': '1', 'show': True},
            'tags_set': {'builtin': {}, 'custom': []}, 'tag_user': {'uid': 7, 'tags': []}, 'room_set': {'plat': 'bili', 'room': 1},
            'storage_clean': {'kind': 'img'}, 'kw_set': {'rules': []}, 'train_install': {'folder': 'D:/x'}, 'train_use': {'folder': 'D:/x'}, 'train_import': {'name': 'a', 'ref_audio': 'D:/a.wav'}, 'hist_merge': {'a': '20261101-1200', 'b': '20261101-1300'},
        }
        before = copy.deepcopy(self.state.snapshot())
        for cmd in valid.COMMAND_FIELDS:
            with self.subTest(cmd=cmd):
                command = {'cmd': cmd, 'rid': cmd, **overrides.get(cmd, {})}
                valid.validate_command(command, server.clean_rules)
                ws = self.websocket([command], {'room': '456'})
                snapshot = ws.sent[0]['data']
                self.assertEqual(snapshot['side']['room'], 456)
                results = [m['data'] for m in ws.sent if m['type'] == 'result']
                self.assertEqual(len(results), 1)
                self.assertEqual((results[0]['ok'], results[0]['rid']), (False, cmd))
                self.assertIn('正在看别的直播间', results[0]['msg'])
        self.assertEqual(self.state.snapshot(), before)
        self.assertEqual(self.bare.calls, [])
        self.assertEqual(len(self.session.calls), 3)
        self.client.start.assert_called_once()

    def test_invalid_room_returns_connect_error(self):
        self.session.replies = [Reply({'data': {}})]
        ws = self.websocket([], {'room': '456'})
        self.assertFalse(ws.sent[0]['data']['ok'])
        self.assertIn('找不到这个直播间', ws.sent[0]['data']['msg'])
        self.client.start.assert_not_called()

    def test_alias_reuses_real_room_client(self):
        self.websocket([], {'room': '456'})
        self.session.replies.append(Reply({'data': {'uid': 99, 'room_id': 456}}))
        ws = self.websocket([], {'room': '12'})
        self.assertEqual(ws.sent[0]['data']['side']['room'], 456)
        self.client.start.assert_called_once()
        self.assertEqual(len(self.session.calls), 4)
