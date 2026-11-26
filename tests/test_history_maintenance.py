import asyncio
import datetime as dt
import gzip
import json
import os
from pathlib import Path
from unittest.mock import patch
import zipfile

import server
import history_maintenance as maintenance
from test_backend import HubTest


class HistoryMaintenanceTests(HubTest):
    def setUp(self):
        super().setUp()
        self.now = dt.datetime(2026, 11, 20, 12).timestamp()
        self.sid = '20260101-1234'
        self.raw = Path(self.history.dm_file(self.sid))
        self.raw.parent.mkdir(parents=True, exist_ok=True)
        brief = {'id': self.sid, 'start': self.now - 60*86400, 'title': '旧场次'}
        self.history.save({'id': self.sid, 'start': brief['start'], 'brief': brief})
        self.rows = [{'uid': n % 2 + 1, 'name': '观众', 'text': f'歌曲 {n}', 't': int(self.now)-1000+n,
                      'face': '', 'guard': 0, 'pos': n+1} for n in range(220)]
        self.raw.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in self.rows), encoding='utf-8')
        os.utime(self.raw, (self.now-40*86400, self.now-40*86400))

    def run_job(self, **kwargs):
        return maintenance.organize(self.root, server.write_json, lambda: True, now=self.now, **kwargs)

    def test_compression_bytes_search_pagination_and_monthly_restart(self):
        original = self.raw.read_bytes()
        before = server.History(123).dm(self.sid)
        result = self.run_job()
        self.assertEqual(result['compressed'], 1)
        self.assertFalse(self.raw.exists())
        self.assertEqual(gzip.open(str(self.raw)+'.gz', 'rb').read(), original)
        after = server.History(123).dm(self.sid)
        self.assertEqual(before, after)
        for q, uid in (('', 0), ('歌曲 1', 0), ('', 2)):
            for page in (None, 100, 20):
                self.assertEqual(server.dm_page(before, page, 30, q, uid), server.dm_page(after, page, 30, q, uid))
        self.assertFalse(self.run_job()['ran'])
        self.assertEqual(len(server.History(123).list()), 1)

    def test_verification_failure_preserves_original_and_index(self):
        raw = self.raw.read_bytes()
        with patch.object(maintenance, 'equal_bytes', return_value=False):
            result = self.run_job()
        self.assertEqual(result['compressed'], 0)
        self.assertTrue(result['pending'])
        self.assertEqual(self.raw.read_bytes(), raw)
        self.assertEqual(len(self.history.list()), 1)

    def test_missing_index_rebuilt_missing_summary_index_kept(self):
        missing = {'id': '20260102-1234', 'start': 1}
        server.write_json(self.history.index_file, [missing])
        result = self.run_job()
        self.assertEqual(result['index_added'], 1)
        self.assertEqual({r['id'] for r in self.history.list()}, {self.sid, missing['id']})

    def test_live_skip_and_live_change_before_commit(self):
        self.state.room['live'] = 1
        result = asyncio.run(maintenance.maintain(self.hub, self.root, server.write_json))
        self.assertFalse(result['ran'])
        self.assertTrue(self.raw.exists())
        allowed = [True]
        def stop(*args):
            allowed[0] = False
            return True
        with patch.object(maintenance, 'equal_bytes', side_effect=stop):
            maintenance.compress_one(self.root, self.raw, lambda: allowed[0])
        self.assertTrue(self.raw.exists())

    def test_batch_continuation_and_protected_files(self):
        for i in range(51):
            path = self.raw.parent / f'20260103-{i:04d}.dm.jsonl'
            path.write_bytes(self.raw.read_bytes())
            os.utime(path, (self.now-40*86400, self.now-40*86400))
        protected = self.root / 'data' / 'dmlog' / 'keep.tmp'
        protected.parent.mkdir(parents=True, exist_ok=True)
        protected.write_bytes(b'keep')
        os.utime(protected, (1, 1))
        tmp = self.raw.parent / (self.sid + '.dm.jsonl.gz.tmp')
        tmp.write_bytes(b'partial')
        os.utime(tmp, (1, 1))
        first = self.run_job()
        self.assertEqual(first['compressed'], 50)
        self.assertTrue(first['pending'])
        second = self.run_job()
        self.assertEqual(second['compressed'], 2)
        self.assertFalse(second['pending'])
        self.assertEqual(protected.read_bytes(), b'keep')
        self.assertFalse(tmp.exists())

    def test_daily_backup_preserves_gzip_and_history_delete_removes_it(self):
        self.run_job()
        with patch.object(server.time, 'strftime', return_value='data-20261120.zip'):
            archive = server.backup_data()
        with zipfile.ZipFile(archive) as z:
            name = f'history/123/{self.sid}.dm.jsonl.gz'
            self.assertEqual(gzip.decompress(z.read(name)), gzip.open(str(self.raw)+'.gz', 'rb').read())
        self.history.delete(self.sid)
        self.assertFalse(Path(str(self.raw)+'.gz').exists())

    def test_current_archive_and_index_temporary_file_protection(self):
        index_tmp = self.raw.parent / 'index.json.tmp'
        index_tmp.write_bytes(b'partial')
        os.utime(index_tmp, (1, 1))
        self.run_job(protected={('123', self.sid)})
        self.assertTrue(self.raw.exists())
        self.assertFalse(index_tmp.exists())

    def test_failed_files_do_not_starve_next_batch(self):
        for i in range(2):
            path = self.raw.parent / f'20260102-{i:04d}.dm.jsonl'
            path.write_bytes(self.raw.read_bytes())
            os.utime(path, (self.now-40*86400, self.now-40*86400))
        with patch.object(maintenance, 'compress_one', side_effect=OSError):
            self.assertTrue(self.run_job(batch=1)['pending'])
        self.assertEqual(self.run_job(batch=1)['compressed'], 1)
        self.assertTrue(self.raw.exists())

    def test_legacy_summary_without_brief_recovers_index(self):
        sid = '20260105-1234'
        row = {'id': sid, 'start': 100, 'end': 200, 'title': '旧版历史', 'dm_total': 8}
        server.write_json(str(self.raw.parent / (sid + '.json')), row)
        self.assertEqual(self.run_job()['index_added'], 1)
        self.assertEqual(next(r for r in self.history.list() if r['id'] == sid), row)

    def test_crossing_calendar_month_does_not_repeat_before_thirty_days(self):
        self.run_job()
        later = self.now + 15 * 86400
        self.assertFalse(maintenance.organize(self.root, server.write_json, lambda: True, now=later)['ran'])
        self.assertTrue(maintenance.organize(self.root, server.write_json, lambda: True, now=self.now+31*86400)['ran'])
