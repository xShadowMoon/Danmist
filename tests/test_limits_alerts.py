"""不联网测试管理操作限制和存档告警。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from backend_limits import OperationError, OperationRate, WS_IMPORT_LIMIT, WS_NORMAL_LIMIT, parse_operation
import server


def finish(coro):
    """AsyncMock 不挂起；直接推进协程，测试不创建网络套接字。"""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    finally:
        coro.close()
    raise AssertionError('测试协程意外挂起')


class LimitsTest(unittest.TestCase):
    def test_normal_limit_counts_utf8_bytes(self):
        prefix = '{"cmd":"song_add","rid":"r1","text":"'
        suffix = '"}'
        remaining = WS_NORMAL_LIMIT - len(prefix + suffix)
        text = prefix + '歌' * (remaining // 3) + 'x' * (remaining % 3) + suffix
        self.assertEqual(len(text.encode()), WS_NORMAL_LIMIT)
        self.assertEqual(parse_operation(text)['cmd'], 'song_add')
        with self.assertRaises(OperationError) as exc:
            parse_operation(text + ' ')
        self.assertEqual(exc.exception.info, {'cmd': 'song_add', 'rid': 'r1'})

    def test_import_3000_songs_and_exact_size_boundary(self):
        rows = [{'name': f'歌名{i}', 'artist': '测试歌手', 'tags': ['现场'],
                 'level': '熟悉', 'note': '中文备注'} for i in range(3000)]
        text = json.dumps({'cmd': 'library_import', 'rows': rows}, ensure_ascii=False)
        exact = text + ' ' * (WS_IMPORT_LIMIT - len(text.encode()))
        self.assertEqual(len(parse_operation(exact)['rows']), 3000)
        with self.assertRaisesRegex(OperationError, '3 MB'):
            parse_operation(exact + ' ')

    def test_invalid_commands_rejected_and_legacy_reset_works(self):
        self.assertEqual(parse_operation('reset'), {'cmd': 'reset'})
        for bad in ['{', '[]', '{"cmd":1}', '{"name":"song"}', '[' * 2000]:
            with self.subTest(bad=bad[:20]), self.assertRaises(OperationError):
                parse_operation(bad)

    def test_sliding_window_and_notice_are_per_connection(self):
        first, second = OperationRate(), OperationRate()
        for i in range(20):
            self.assertTrue(first.allow(i / 100))
        self.assertFalse(first.allow(1.99))
        self.assertTrue(first.should_notify(1.99))
        self.assertFalse(first.should_notify(2))
        self.assertTrue(second.allow(1.99))
        self.assertTrue(first.allow(2))
        self.assertFalse(first.allow(2))
        self.assertTrue(first.should_notify(4))


class ArchiveAlertTest(unittest.TestCase):
    def test_dmlog_failure_and_summary_failure_share_one_incident(self):
        state = SimpleNamespace(archive_pending=None)
        dmlog = SimpleNamespace(repair_write=True)
        alert = server.Alerts(None, persist=False)
        alert.send = AsyncMock(return_value=True)
        for stamp in [1000, 1299]:
            with patch.object(server.time, 'time', return_value=stamp):
                finish(alert.check_archive(state, dmlog))
        alert.send.assert_not_awaited()
        with patch.object(server.time, 'time', return_value=1300):
            finish(alert.check_archive(state, dmlog))
        self.assertEqual(alert.send.await_count, 1)
        self.assertIn('5 分钟', alert.send.await_args.args[0])
        dmlog.repair_write = False
        state.archive_pending = {'id': 'archive'}
        with patch.object(server.time, 'time', return_value=1400):
            finish(alert.check_archive(state, dmlog))
        self.assertEqual(alert.send.await_count, 1)
        state.archive_pending = None
        with patch.object(server.time, 'time', return_value=1500):
            finish(alert.check_archive(state, dmlog))
            finish(alert.check_archive(state, dmlog))
        self.assertEqual(alert.send.await_count, 2)
        self.assertIn('恢复', alert.send.await_args.args[0])

    def test_disk_error_does_not_silence_alert_and_state_is_retried(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as scratch, patch.object(server, 'DIR', scratch):
            alert = server.Alerts(None)
            alert.send = AsyncMock(return_value=True)
            state, log = SimpleNamespace(archive_pending={1: 2}), SimpleNamespace(repair_write=False)
            with patch.object(server, 'write_json', side_effect=OSError('disk full')):
                with patch.object(server.time, 'time', return_value=100):
                    finish(alert.check_archive(state, log))
                with patch.object(server.time, 'time', return_value=400):
                    finish(alert.check_archive(state, log))
            self.assertTrue(alert.unsaved)
            self.assertEqual(alert.send.await_count, 1)
            with patch.object(server.time, 'time', return_value=430):
                finish(alert.check_archive(state, log))
            resumed = server.Alerts(None)
            self.assertTrue(resumed.state['archive']['sent'])
            resumed.send = AsyncMock(side_effect=[False, True])
            state.archive_pending = None
            with patch.object(server.time, 'time', return_value=500):
                finish(resumed.check_archive(state, log))
                self.assertIn('archive', resumed.state)
                finish(resumed.check_archive(state, log))
                self.assertNotIn('archive', resumed.state)
