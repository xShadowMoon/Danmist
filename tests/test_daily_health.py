import asyncio
import datetime as dt
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import zipfile

import server
import daily_health as health
from test_backend import TemporaryDataTest


class DailyHealthTests(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        self.now = dt.datetime(2026, 11, 20, 10).timestamp()
        (self.root / 'data' / 'accounts').mkdir(parents=True)
        self.backups = self.root / '备份' / '数据'
        self.backups.mkdir(parents=True)
        with zipfile.ZipFile(self.backups / 'data-20261120.zip', 'w') as z:
            z.writestr('fake.json', '{}')

    def checks(self, free=10*health.GB, total=100*health.GB):
        with patch.object(health.shutil, 'disk_usage', return_value=SimpleNamespace(free=free, total=total)):
            return health.disk_checks(self.root, self.now)

    def test_good_disk_sizes_backup_accounts(self):
        rows = self.checks()
        self.assertTrue(all(r['ok'] for r in rows))
        self.assertGreater(next(r for r in rows if r['id'] == 'backup_size')['bytes'], 0)

    def test_low_space_by_gigabytes_or_percent_and_missing_bad_backup(self):
        for free, total in ((4*health.GB, 10*health.GB), (6*health.GB, 200*health.GB)):
            self.assertFalse(self.checks(free, total)[0]['ok'])
        (self.backups / 'data-20261120.zip').write_bytes(b'broken')
        self.assertFalse(next(r for r in self.checks() if r['id'] == 'backup')['ok'])
        with zipfile.ZipFile(self.backups / 'data-20261119.zip', 'w') as z:
            z.writestr('fake.json', '{}')
        self.assertTrue(next(r for r in self.checks() if r['id'] == 'backup')['ok'])

    def test_account_uses_mtime_without_reading_credentials(self):
        file = self.root / 'data' / 'accounts' / ('a'*24 + '.json')
        file.write_text('not-even-json', encoding='utf-8')
        stamp = self.now - 170 * 86400
        os.utime(file, (stamp, stamp))
        row = next(r for r in self.checks() if r['id'] == 'accounts')
        self.assertFalse(row['ok'])
        self.assertEqual(row['count'], 1)
        self.assertEqual(file.stat().st_mtime, stamp)

    def test_normal_silent_restart_and_failed_send_retry(self):
        async def run():
            check = health.DailyHealth(self.root, server.write_json)
            sender = AsyncMock(return_value=True)
            good = [{'id': 'disk', 'ok': True, 'detail': '正常'}]
            with patch.object(health, 'disk_checks', return_value=good), patch.object(health, 'tunnel_check', new=AsyncMock(return_value=True)):
                self.assertFalse(await check.run({'bili_ok': True, 'login_ok': True}, None, '', sender, now=self.now))
                sender.assert_not_awaited()
                again = health.DailyHealth(self.root, server.write_json)
                self.assertFalse(await again.run({}, None, '', sender, now=self.now))
            sender = AsyncMock(side_effect=[False, True])
            with patch.object(health, 'disk_checks', return_value=good), patch.object(health, 'tunnel_check', new=AsyncMock(return_value=False)):
                tomorrow = self.now + 86400
                self.assertFalse(await check.run({'bili_ok': False, 'login_ok': False}, None, '', sender, now=tomorrow))
                self.assertTrue(await check.run({}, None, '', sender, now=tomorrow + 30))
                text = sender.await_args.args[0]
                self.assertIn('外网', text)
                self.assertIn('机器人', text)
                again = health.DailyHealth(self.root, server.write_json)
                self.assertFalse(await again.run({}, None, '', sender, now=tomorrow + 60))
                self.assertEqual(sender.await_count, 2)
        asyncio.run(run())

    def test_disabled_and_before_hour_do_not_send(self):
        async def run():
            check = health.DailyHealth(self.root, server.write_json, persist=False)
            sender = AsyncMock(return_value=True)
            with patch.object(health, 'disk_checks', return_value=[]), patch.object(health, 'tunnel_check', new=AsyncMock(return_value=False)):
                await check.run({}, None, '', sender, enabled=False, now=self.now)
                sender.assert_not_awaited()
                self.assertTrue(check.snapshot()['checks'])
                check = health.DailyHealth(self.root, server.write_json, persist=False)
                await check.run({}, None, '', sender, now=self.now - 2*3600)
                self.assertEqual(check.snapshot()['checked_at'], 0)
        asyncio.run(run())
