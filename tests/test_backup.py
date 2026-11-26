"""一键备份 / 恢复（2026-11-26）。"""
import json
import os

import server
from test_backend import TemporaryDataTest


class BackupTests(TemporaryDataTest):
    def write(self, rel, text):
        p = self.root / 'data' / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')

    def test_backup_list_and_restore(self):
        self.write('a.json', '"old"')
        self.write('imgcache/x.webp', 'cache')
        daily = server.backup_data()
        self.assertIsNone(server.backup_data())  # 每天的一天只做一份
        manual = server.backup_data(tag='手动')
        self.assertTrue(os.path.exists(daily) and os.path.exists(manual))
        names = [r['name'] for r in server.list_backups()]
        self.assertIn(os.path.basename(manual), names)
        # 之后改了数据，再从那份恢复
        self.write('a.json', '"new"')
        self.write('b.json', '"extra"')
        server.write_json(str(self.root / 'data' / server.RESTORE_FILE), {'name': os.path.basename(manual)})
        self.assertEqual(server.apply_pending_restore(), os.path.basename(manual))
        self.assertEqual((self.root / 'data' / 'a.json').read_text(encoding='utf-8'), '"old"')
        self.assertFalse((self.root / 'data' / 'b.json').exists())
        self.assertTrue((self.root / 'data' / 'imgcache' / 'x.webp').exists())  # 缓存不动
        self.assertTrue(any('恢复前' in r['name'] for r in server.list_backups()))  # 换之前的也存了一份
        self.assertIsNone(server.apply_pending_restore())  # 只做一次

    def test_bad_restore_name_does_nothing(self):
        self.write('a.json', '"keep"')
        server.write_json(str(self.root / 'data' / server.RESTORE_FILE), {'name': '../../etc.zip'})
        self.assertFalse(server.apply_pending_restore())
        self.assertEqual((self.root / 'data' / 'a.json').read_text(encoding='utf-8'), '"keep"')
