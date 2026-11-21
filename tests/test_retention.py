import asyncio
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import retention
import server


class RetentionTests(unittest.TestCase):
    def setUp(self):
        # 正式配置下历史不自动移走（retention.HISTORY_* 设得很大）；这里换回原来的期限，测冷存档这套机制本身还对不对
        history_limits = patch.multiple(retention, HISTORY_DAYS=365, HISTORY_MAX=1000)
        history_limits.start()
        self.addCleanup(history_limits.stop)
        # 所有文件都在副本的测试临时目录，绝不使用真实 data。
        tests = Path(__file__).resolve().parent
        self.tmp = tempfile.TemporaryDirectory(dir=tests, prefix='retention-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.now = int(time.time())
        self.room = '1000001'
        self.patcher = patch.object(server, 'DIR', self.tmp.name)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(asyncio.set_event_loop, None)
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        asyncio.set_event_loop(self.loop)
        self.state = server.State(int(self.room))
        self.history = server.History(int(self.room))
        self.hub = server.Hub(self.state, self.history)
        self.hub.emit = lambda *a, **k: None

    def write(self, path, body):
        server.write_json(str(path), body)
        return path

    def aged(self, path, days):
        then = self.now - days * retention.DAY
        os.utime(path, (then, then))

    def test_offline_keeps_recent_active_unrecognized_and_unverifiable(self):
        folder = self.data / 'offline' / self.room
        expired = self.now - 61 * retention.DAY
        old = self.write(folder / '20250101-0000.json', {'from':0,'to':expired,'dm':[]})
        active = self.write(folder / f'{self.state.archive_id}.json', {'from':0,'to':expired,'dm':[]})
        recently_used = self.write(folder / '20250101-0001.json', {'from':0,'to':self.now,'dm':[]})
        unreadable = self.write(folder / '20250101-0002.json', ['not an archive'])
        other = self.write(folder / 'personal.json', {'from':0,'to':expired,'dm':[]})
        for path in (old, active, recently_used, unreadable, other):
            self.aged(path, 61)
        retention.prune_offline(self.data, self.room, {self.state.archive_id}, self.now)
        self.assertFalse(old.exists())
        for path in (active, recently_used, unreadable, other):
            self.assertTrue(path.is_file())

    def test_accounts_idle_and_cap(self):
        accounts = server.Accounts()
        expired = accounts.save('synthetic-cookie', 1, '测试一')
        active = accounts.save('synthetic-cookie', 2, '测试二')
        touched = accounts.save('synthetic-cookie', 3, '测试三')
        old_path = Path(accounts._path(expired))
        active_path = Path(accounts._path(active))
        touched_path = Path(accounts._path(touched))
        self.aged(old_path, retention.ACCOUNT_IDLE_DAYS + 1)
        self.aged(active_path, 4)
        self.aged(touched_path, 3)
        self.assertIsNone(accounts.get(expired))
        self.assertEqual(accounts.of_uid(2)['uid'], 2)
        self.assertGreater(active_path.stat().st_mtime, self.now - 1)
        self.assertEqual(int(touched_path.stat().st_mtime), self.now - 3 * retention.DAY)
        with patch.object(retention, 'ACCOUNT_MAX', 2):
            with self.assertRaisesRegex(ValueError, '已保存'):
                accounts.save('synthetic-cookie', 4, '测试四')
        self.assertFalse(old_path.exists())
        self.assertTrue(active_path.exists())
        self.assertTrue(touched_path.exists())

    def test_guard_prune_and_notes_cap(self):
        expired = self.now - 366 * retention.DAY
        young = self.now - 300 * retention.DAY
        guard = self.hub.guardbook
        guard.data = {'old':{'until':expired},'recent':{'until':young},'active':{'until':self.now + 1}}
        guard.prune(self.now)
        self.assertEqual(set(guard.data), {'recent','active'})
        self.assertEqual(json.loads(Path(guard.file).read_text(encoding='utf-8')), guard.data)
        with patch.object(retention, 'NOTES_MAX', 1):
            notes = self.hub.notes
            notes.set(1, '一', '已整理')
            with self.assertRaises(ValueError):
                notes.set(2, '二', '第二条')
            notes.set(1, '一', '更新备注')
            self.assertEqual(notes.data['1']['note'], '更新备注')
            notes.set(1, '一', '')
            notes.set(2, '二', '第二条')

    def test_emots_bounded_without_changing_snapshot_shape(self):
        with patch.object(retention, 'EMOTS_MAX', 2):
            self.hub.learn_emots({'[旧]':'https://example.test/1','[新]':'https://example.test/2'})
            self.hub.learn_emots({'[最新]':'https://example.test/3','[无效]':'a' * 2049})
        self.assertEqual(set(self.hub.emots), {'[新]', '[最新]'})
        self.assertEqual(json.loads(Path(self.hub.emots_file).read_text(encoding='utf-8')), self.hub.emots)

    def test_legacy_and_unmatched_logs_are_never_guessed(self):
        old = self.state.archive_id
        self.state.room['live'] = 1
        self.state.was_live = True
        self.hub.danmaku(1, '测试', '', '待核对')
        self.hub.new_session('手动清零')
        stored = self.data / 'dmlog' / f'{self.room}-{old}.jsonl'
        self.assertTrue(stored.exists())
        history_dm = Path(self.history.dm_file(old))
        history_dm.write_text('{"text":"不完整"}\n', encoding='utf-8')
        legacy = stored.parent / f'{self.room}.jsonl'
        legacy.write_text('{"text":"旧版记录"}\n', encoding='utf-8')
        index = {row['id']: row for row in self.history._index()}
        unresolved = retention.prune_dmlog(self.data, self.room, index, {self.state.archive_id})
        self.assertEqual(unresolved, {old})
        self.assertTrue(stored.exists())
        self.assertTrue(legacy.exists())

    def test_same_second_offline_dm_stays_in_archive_and_can_cleanup(self):
        before = self.state.archive_id
        with patch.object(server.time, 'time', return_value=self.now):
            self.hub.room_update(live=1, title='测试')
            self.hub.danmaku(0, '测试', '', '直播弹幕')
            self.hub.room_update(live=0)
            self.hub.close_broadcast('下播')
            self.hub.danmaku(1, '测试', '', '同秒下播弹幕')
            self.hub.new_session('自动结算')
        self.assertEqual([row['text'] for row in self.history.dm(before)], ['直播弹幕'])
        offline = json.loads((self.data / 'offline' / self.room / f'{before}.json').read_text(encoding='utf-8'))
        self.assertEqual([row['text'] for row in offline['dm']], ['同秒下播弹幕'])
        stored = self.data / 'dmlog' / f'{self.room}-{before}.jsonl'
        self.assertTrue(stored.exists())
        index = {row['id']: row for row in self.history._index()}
        self.assertEqual(retention.prune_dmlog(self.data, self.room, index, {self.state.archive_id}), set())
        self.assertFalse(stored.exists())

    def test_segment_capacity_archives_active_data(self):
        self.hub.room_update(live=1, title='测试')
        self.state.live_start = self.now - 900
        before = self.state.archive_id
        self.hub.danmaku(1, '测试', '', '第一条')
        self.hub.danmaku(2, '测试', '', '第二条')
        with patch.object(retention, 'SEGMENT_DM_ROWS', 2):
            self.hub.rotate_large_segment()
        self.assertNotEqual(self.state.archive_id, before)
        self.assertEqual(self.state.live_start, self.now - 900)
        self.assertEqual([row['text'] for row in self.history.dm(before)], ['第一条','第二条'])
        self.assertEqual(self.history.get(before)['reason'], '容量分段')

    def test_failed_segment_rotation_preserves_current_dm_and_backoff(self):
        self.hub.room_update(live=1)
        before = self.state.archive_id
        self.hub.danmaku(1, '测试', '', '不能丢')
        with patch.object(retention, 'SEGMENT_DM_ROWS', 1), patch.object(self.history, 'save', side_effect=OSError):
            self.hub.rotate_large_segment()
        self.assertEqual(self.state.archive_id, before)
        self.assertEqual(len(self.hub.dmlog.items), 1)
        self.assertGreater(self.hub.rotate_after, time.monotonic())

    def test_history_moves_only_verified_old_archives_and_protects_current(self):
        old = self.now - 400 * retention.DAY
        sid = '20200101-1234'
        row = {'id':sid,'start':old,'end':old + 100}
        self.history.save({'id':sid,'brief':row})
        self.history.save({'id':self.state.archive_id,'brief':{'id':self.state.archive_id,'start':old,'end':old + 100}})
        summary = Path(self.history.dir) / f'{sid}.json'
        raw = summary.read_bytes()
        self.loop.run_until_complete(server.maintain_data(self.hub))
        self.assertIsNone(self.history.get(sid))
        self.assertIsNotNone(self.history.get(self.state.archive_id))
        self.assertEqual([r['id'] for r in self.history.list()], [self.state.archive_id])
        archive, = (self.root / '备份' / '历史冷存档').glob('*.zip')
        with zipfile.ZipFile(archive) as f:
            self.assertEqual(f.read(summary.name), raw)
            self.assertEqual(json.loads(f.read('index.json')), [row])
            self.assertIsNone(f.testzip())

    def test_backup_failure_retains_source_and_history_index(self):
        end = self.now - 400 * retention.DAY
        sid = '20200101-1234'
        row = {'id':sid,'start':end-100,'end':end}
        self.history.save({'id':sid,'brief':row})
        with patch.object(retention.zipfile.ZipFile, 'testzip', return_value='bad'):
            with self.assertRaises(OSError):
                self.loop.run_until_complete(server.maintain_data(self.hub))
        self.assertIsNotNone(self.history.get(sid))
        self.assertEqual(self.history.list(), [row])
