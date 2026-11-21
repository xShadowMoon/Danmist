import asyncio
import copy
import datetime
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import server
from workbench import trusted_origin


def run_without_io(coro):
    """这些协程只等待立即返回的替身，不创建 Windows 事件循环的本机套接字。"""
    try:
        coro.send(None)
    except StopIteration as finished:
        return finished.value
    finally:
        coro.close()
    raise AssertionError('离线测试遇到了未替换的等待操作')


class TemporaryDataTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='xiaowu-tests-', dir=Path(__file__).resolve().parent)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.enterContext(patch.object(server, 'DIR', directory.name))


class HubTest(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        self.state = server.State(123)
        self.history = server.History(123)
        self.hub = server.Hub(self.state, self.history)
        # 只拦网页推送；仍实际写入临时目录，验证重启与历史读取。
        self.hub.emit = lambda *args, **kwargs: None
        self.hub.emit_admin = lambda *args, **kwargs: None


class ArchiveTests(HubTest):
    def open_broadcast(self):
        self.state.live_start = self.state.session_start
        self.hub.room_update(live=1, title='测试直播')
        self.hub.danmaku(1, '测试观众', '', '开播了')
        self.hub.gift(1, '测试观众', '', '礼物', 2, 60)
        return self.state.archive_id

    def test_end_broadcast_saves_summary_and_full_danmaku(self):
        archive_id = self.open_broadcast()
        for number in range(305):
            self.hub.danmaku(1, '测试观众', '', f'消息 {number}')
        self.assertLess(len(self.state.dm), len(self.hub.dmlog.items))
        server.Handler(self.hub).handle(None, {'cmd': 'PREPARING'})

        saved = server.History(123)
        row = saved.get(archive_id)
        self.assertEqual(row['title'], '测试直播')
        self.assertEqual(row['flow']['gift'], 60)
        self.assertEqual(row['dm_total'], 306)
        self.assertEqual(saved.list()[0]['id'], archive_id)
        self.assertEqual(len(saved.dm(archive_id)), 306)
        self.assertEqual(saved.dm(archive_id)[-1]['text'], '消息 304')
        self.assertTrue(self.state.summarized)
        self.assertEqual(self.state.room['live'], 0)

    def test_two_resets_in_same_broadcast_keep_three_archives(self):
        first = self.open_broadcast()
        broadcast_start = self.state.live_start
        self.hub.new_session('手动清零')
        second = self.state.archive_id
        self.assertTrue(self.state.was_live)
        self.assertEqual(self.state.live_start, broadcast_start)
        self.hub.danmaku(1, '测试观众', '', '第一段清零后')
        self.hub.new_session('手动清零')
        third = self.state.archive_id
        self.hub.danmaku(1, '测试观众', '', '第二段清零后')
        self.hub.close_broadcast('下播')

        self.assertEqual({row['id'] for row in self.history.list()}, {first, second, third})
        self.assertEqual(self.history.dm(first)[0]['text'], '开播了')
        self.assertEqual(self.history.dm(second)[0]['text'], '第一段清零后')
        self.assertEqual(self.history.dm(third)[0]['text'], '第二段清零后')

    def test_failed_archive_retries_original_end_and_survives_restart(self):
        archive_id = self.open_broadcast()
        end = self.state.last_activity
        with patch.object(self.history, 'save', side_effect=OSError('模拟磁盘写入失败')):
            self.hub.close_broadcast('下播', end)
        self.assertFalse(self.state.summarized)
        self.assertEqual(self.state.archive_pending['end'], end)
        self.assertEqual(self.history.list(), [])
        with patch.object(server.time, 'time', return_value=end + 10):
            self.hub.danmaku(2, '测试观众', '', '下播后的弹幕')
            self.hub.gift(2, '测试观众', '', '下播后礼物', 1, 20)
        self.assertTrue(self.state.save())
        self.assertTrue(self.hub.dmlog.flush())

        state = server.State(123)
        saved = server.History(123)
        hub = server.Hub(state, saved)
        hub.emit = lambda *args, **kwargs: None
        hub.close_broadcast('重试', end + 100)
        self.assertIsNone(state.archive_pending)
        self.assertTrue(state.summarized)
        self.assertEqual(saved.get(archive_id)['end'], end)
        self.assertEqual(saved.get(archive_id)['flow']['gift'], 60)
        self.assertEqual([d['text'] for d in saved.dm(archive_id)], ['开播了'])
        self.assertEqual([d['text'] for d in hub.dmlog.items], ['开播了', '下播后的弹幕'])

    def test_failed_log_write_retries_without_duplicates(self):
        self.open_broadcast()
        self.assertTrue(self.hub.dmlog.flush())
        self.hub.danmaku(1, '测试观众', '', '第二条')
        log = self.hub.dmlog
        actual_open = io.open

        def interrupted_open(path, mode='r', **kwargs):
            if path == log.file and mode == 'a':
                # 模拟部分写入已落盘后才抛错，重试不能把这条再追加一遍。
                with actual_open(path, mode, **kwargs) as stream:
                    stream.write(log.pending[0] + '\n')
                raise OSError('模拟部分写入后失败')
            return actual_open(path, mode, **kwargs)

        with patch('builtins.open', side_effect=interrupted_open):
            self.assertFalse(log.flush())
        self.assertTrue(log.repair_write)
        self.assertEqual(len(log.pending), 1)
        self.assertTrue(log.flush())
        self.assertFalse(log.repair_write)
        self.assertEqual([d['text'] for d in server.read_jsonl(log.file)], ['开播了', '第二条'])

    def test_new_broadcast_detected_by_poll_archives_previous_segment(self):
        archive_id = self.open_broadcast()
        next_start = self.state.live_start + 120

        class RoomReply:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                pass

            async def json(self, **kwargs):
                return {'data': {'live_status': 1, 'live_time': datetime.datetime.fromtimestamp(
                    next_start, server.BJ).strftime('%Y-%m-%d %H:%M:%S'), 'title': '下一场'}}

        async def stop_after_one_poll(waiting, timeout):
            waiting.close()
            raise asyncio.CancelledError

        session = SimpleNamespace(get=lambda *args, **kwargs: RoomReply())
        with patch.object(server.time, 'time', return_value=next_start), \
                patch.object(server.asyncio, 'wait_for', side_effect=stop_after_one_poll):
            with self.assertRaises(asyncio.CancelledError):
                run_without_io(server.poll_room(self.hub, session, 123))

        self.assertNotEqual(self.state.archive_id, archive_id)
        self.assertEqual(self.state.live_start, next_start)
        self.assertEqual(self.state.meta['title'], '下一场')
        self.assertEqual(self.history.get(archive_id)['reason'], '自动结算')
        self.assertEqual(self.history.dm(archive_id)[0]['text'], '开播了')
        self.assertEqual(self.hub.dmlog.items, [])


class DanmakuPageTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {'i': 0, 'uid': 1, 'name': 'Misty', 'text': '你好'},
            {'i': 1, 'uid': 2, 'name': '小雨', 'text': '点歌 MISTY'},
            {'i': 2, 'uid': 1, 'name': 'Misty', 'text': '谢谢'},
            {'i': 3, 'uid': 2, 'name': '小雨', 'text': '再见'},
            {'i': 4, 'uid': 3, 'name': '路人', 'text': '最后一句'},
        ]

    def test_backward_cursor_has_no_gaps_or_duplicates(self):
        latest = server.dm_page(self.items, limit=2)
        middle = server.dm_page(self.items, before=latest['next'], limit=2)
        first = server.dm_page(self.items, before=middle['next'], limit=2)
        self.assertEqual(latest['items'], self.items[-2:])
        self.assertEqual(middle['items'], self.items[1:3])
        self.assertEqual(first['items'], self.items[:1])
        self.assertTrue(latest['more'])
        self.assertTrue(middle['more'])
        self.assertFalse(first['more'])

    def test_search_name_text_and_uid(self):
        self.assertEqual(server.dm_page(self.items, q=' misty ')['items'], self.items[:3])
        self.assertEqual(server.dm_page(self.items, uid=2)['items'], [self.items[1], self.items[3]])
        self.assertEqual(server.dm_page(self.items, q='MISTY', uid=2)['items'], [self.items[1]])
        self.assertEqual(server.dm_page(self.items, uid=404)['items'], [])


class PermissionTests(unittest.TestCase):
    PORT = 8390
    PUBLIC = 'https://live.example.com'
    LOCAL_HOST = '127.0.0.1:8390'
    PUBLIC_HOST = 'live.example.com'
    KEY = 'only-for-unit-tests'

    def request(self, host, origin=None, *, remote='127.0.0.1', tunneled=False, query=None, cookies=None):
        headers = {'Origin': origin} if origin is not None else {}
        if tunneled:
            headers['CF-Connecting-IP'] = '192.0.2.21'
        return SimpleNamespace(host=host, headers=headers, remote=remote,
                               query=query or {}, cookies=cookies or {})

    def test_local_browser_and_http_access(self):
        for host in [self.LOCAL_HOST, 'localhost:8390', '[::1]:8390']:
            with self.subTest(host=host):
                origin = 'http://' + host
                remote = '::1' if host.startswith('[') else '127.0.0.1'
                self.assertTrue(trusted_origin(origin, host, self.PUBLIC, self.PORT))
                self.assertTrue(server.is_admin(self.request(host, origin, remote=remote), self.KEY, self.PORT))
        self.assertTrue(server.is_admin(self.request(self.LOCAL_HOST), self.KEY, self.PORT))

    def test_tunnel_does_not_inherit_loopback_admin(self):
        req = self.request(self.PUBLIC_HOST, self.PUBLIC, tunneled=True)
        self.assertTrue(trusted_origin(self.PUBLIC, self.PUBLIC_HOST, self.PUBLIC, self.PORT))
        self.assertFalse(server.is_admin(req, self.KEY, self.PORT))
        self.assertFalse(server.is_admin(self.request(self.LOCAL_HOST, tunneled=True), self.KEY, self.PORT))
        self.assertFalse(server.is_admin(self.request(self.PUBLIC_HOST, self.PUBLIC), self.KEY, self.PORT))
        req.query['admin'] = '错的密钥'
        self.assertFalse(server.is_admin(req, self.KEY, self.PORT))
        req.query['admin'] = self.KEY
        self.assertTrue(server.is_admin(req, self.KEY, self.PORT))
        req.query.clear()
        req.cookies['xwadmin'] = self.KEY
        self.assertTrue(server.is_admin(req, self.KEY, self.PORT))

    def test_wrong_or_missing_websocket_origin_rejected(self):
        for origin in ('https://foreign.invalid', 'null', ''):
            with self.subTest(origin=origin):
                self.assertFalse(trusted_origin(origin, self.LOCAL_HOST, self.PUBLIC, self.PORT))
        req = self.request(self.LOCAL_HOST, 'https://foreign.invalid')
        self.assertFalse(server.is_admin(req, self.KEY, self.PORT))
        self.assertFalse(trusted_origin('http://' + self.LOCAL_HOST, 'wrong.invalid', self.PUBLIC, self.PORT))

    def test_public_view_removes_private_fields_at_every_depth(self):
        private = {'total': 600, 'flow': {'gift': 600}, 'income': 300,
                   'rank': [{'spend': 600}], 'gift_stats': [{'yuan': 600}],
                   'viewers': [[1, '测试观众', 2, 600, 1]], 'notes': {'1': '私人备注'},
                   'library': [{'backing': 'https://example.invalid/track'}],
                   'users': [{'uid': 1, 'name': '测试观众', 'spend': 600}],
                   'items': [{'user': {'uid': 1, 'spend': 600}, 'gift': {'yuan': 50},
                              'sc': {'price': 30}, 'stats': {'income': 300}}]}
        old = copy.deepcopy(private)
        self.assertEqual(server.public_view(private), {'users': [{'uid': 1, 'name': '测试观众'}],
                                                      'items': [{'user': {'uid': 1}, 'gift': {'yuan': 50},
                                                                 'sc': {'price': 30}, 'stats': {}}]})
        self.assertEqual(private, old)


class SongTests(HubTest):
    def test_pending_duplicates_merge(self):
        self.hub.song_cmd('song_add', text='Alpha\n alpha \nBeta\nAlpha')
        self.hub.song_cmd('song_add', text='ALPHA')
        self.assertEqual([row['name'] for row in self.state.songs], ['Alpha', 'Beta'])

    def test_completion_advances_queue_and_request(self):
        self.hub.danmaku(1, '测试观众', '', '点歌 Alpha')
        self.hub.song_cmd('song_add', text='Alpha\nBeta\nGamma')
        first, second, third = self.state.songs
        self.hub.song_cmd('song_now', first['id'])
        self.hub.song_cmd('song_done', first['id'], options={'done': True})
        self.assertTrue(first['done'])
        self.assertTrue(second.get('now'), '唱完后应自动把下一首设为正在唱')
        self.assertFalse(third.get('now', False))
        self.assertTrue(self.state.reqs[0]['done'])

    def test_undo_and_repeat_do_not_double_count_even_after_reload(self):
        self.hub.song_cmd('song_add', text='Alpha')
        first_id = self.state.songs[0]['id']
        self.hub.song_cmd('song_done', first_id, options={'done': True})
        state = server.State(123)
        hub = server.Hub(state, server.History(123))
        hub.emit = lambda *args, **kwargs: None
        hub.song_cmd('song_done', first_id, options={'done': False})
        hub.song_cmd('song_done', first_id, options={'done': True})
        hub.song_cmd('song_done', first_id, options={'done': True})
        self.assertEqual(hub.songbook['Alpha']['n'], 1)

    def test_move_up_and_down(self):
        self.hub.song_cmd('song_add', text='Alpha\nBeta\nGamma')
        first, _, third = self.state.songs
        self.hub.song_cmd('song_move', third['id'], options={'direction': -1})
        self.assertEqual([x['name'] for x in self.state.songs], ['Alpha', 'Gamma', 'Beta'])
        self.hub.song_cmd('song_move', first['id'], options={'direction': 1})
        self.assertEqual([x['name'] for x in self.state.songs], ['Gamma', 'Alpha', 'Beta'])

    def test_only_one_current_song(self):
        self.hub.song_cmd('song_add', text='Alpha\nBeta')
        first, second = self.state.songs
        self.hub.song_cmd('song_now', first['id'])
        self.hub.song_cmd('song_now', second['id'])
        self.assertEqual([x['id'] for x in self.state.songs if x.get('now')], [second['id']])

    def test_stale_next_command_cannot_skip_another_song(self):
        self.hub.song_cmd('song_add', text='Alpha\nBeta')
        first_id = self.state.songs[0]['id']
        self.hub.song_cmd('song_now', first_id)
        self.hub.song_cmd('song_next', options={'expected_now': first_id})
        with self.assertRaises(ValueError):
            self.hub.song_cmd('song_next', options={'expected_now': first_id})
        self.assertEqual([x['name'] for x in self.state.songs if x.get('now')], ['Beta'])


class LibraryTests(HubTest):
    def test_invalid_import_is_atomic(self):
        self.hub.library_cmd('library_save', {'song': {'name': '已存在', 'artist': '测试歌手'}})
        saved = Path(self.hub.songbook_file).read_bytes()
        old = copy.deepcopy(self.hub.songbook)
        for invalid in ('not-an-object', {'name': ''}, {'name': '坏格式', 'tags': {}},
                        {'name': '坏链接', 'backing': 'file:///not-a-web-url'},
                        {'name': '坏级别', 'level': '不存在'}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.hub.library_cmd('library_import', {'rows': [{'name': '不得部分保存'}, invalid]})
                self.assertEqual(self.hub.songbook, old)
                self.assertEqual(Path(self.hub.songbook_file).read_bytes(), saved)

    def test_full_songbook_evicts_unedited_entry_first(self):
        self.hub.songbook = {'有歌手': {'artist': '测试歌手', 'n': 0, 'last': 0},
                             '标了拿手': {'level': '拿手', 'n': 0, 'last': 0},
                             '暂停点歌': {'available': False, 'n': 0, 'last': 0},
                             '没有资料': {'n': 1, 'last': 5}}
        with patch.object(server, 'SONGBOOK_MAX', 4):
            self.hub.song_cmd('song_add', text='新歌')
        self.assertEqual(set(self.hub.songbook), {'有歌手', '标了拿手', '暂停点歌', '新歌'})

    def test_full_curated_songbook_preserves_all_rows(self):
        self.hub.songbook = {'有歌手': {'artist': '测试歌手', 'n': 0, 'last': 0},
                             '标了拿手': {'level': '拿手', 'n': 0, 'last': 0}}
        with patch.object(server, 'SONGBOOK_MAX', 2):
            self.hub.song_cmd('song_add', text='只加入歌单')
        self.assertEqual(set(self.hub.songbook), {'有歌手', '标了拿手'})
        self.assertEqual([x['name'] for x in self.state.songs], ['只加入歌单'])


class AlertTests(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        self.send = AsyncMock(return_value=True)
        self.now = 1000
        self.enterContext(patch.object(server.time, 'time', side_effect=lambda: self.now))

    def check(self, alerts, bad):
        run_without_io(alerts.check('bili', bad, 60,
                                    lambda minutes: f'断开 {minutes} 分钟',
                                    lambda minutes: f'恢复，断开 {minutes} 分钟'))

    def test_short_interruption_is_silent(self):
        alerts = server.Alerts(None)
        alerts.send = self.send
        self.check(alerts, True)
        self.now += 59
        self.check(alerts, False)
        self.send.assert_not_awaited()
        self.assertEqual(alerts.state, {})

    def test_one_down_alert_then_recovery_across_restart(self):
        alerts = server.Alerts(None)
        alerts.send = self.send
        self.check(alerts, True)
        self.now += 60
        self.check(alerts, True)
        self.send.assert_awaited_once_with('断开 1 分钟')

        restarted = server.Alerts(None)
        restarted.send = self.send
        self.now += 60
        self.check(restarted, True)
        self.send.assert_awaited_once_with('断开 1 分钟')
        self.check(restarted, False)
        self.assertEqual([call.args[0] for call in self.send.await_args_list],
                         ['断开 1 分钟', '恢复，断开 2 分钟'])
        self.check(restarted, False)
        self.assertEqual(self.send.await_count, 2)
        self.assertEqual(server.Alerts(None).state, {})
