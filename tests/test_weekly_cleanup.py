"""临时目录验证清理边界；不访问真实数据目录。"""
import os
import time
from unittest.mock import patch

from test_backend import TemporaryDataTest
import retention
import server


class WeeklyTests(TemporaryDataTest):
    def file(self, relative, days):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('abc', encoding='utf-8')
        stamp = time.time() - days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_only_expired_allowed_files_removed_and_weekly_marker(self):
        remove = [self.file('data/old.tmp', 2), self.file('data/sub/file.json.tmp', 2),
                  self.file('data/imgcache/' + 'a' * 40 + '.webp', 31), self.file('demo-old.log', 15), self.file('test-old.log', 15)]
        keep = [self.file(p, days) for p, days in [('data/fresh.tmp', .5), ('data/keep.json', 90),
                ('data/history/old.tmp', 90), ('data/dmlog/old.tmp', 90), ('data/offline/old.tmp', 90),
                ('data/accounts/old.tmp', 90), ('备份/old.tmp', 90), ('static/old.tmp', 90),
                ('data/movie.mp4', 90), ('server.log.1', 90), ('demo-new.log', 1), ('test-new.log', 1),
                ('data/imgcache/' + 'b' * 40 + '.webp', 2)]]
        result = retention.weekly_cleanup(self.root, server.write_json)
        self.assertEqual(result, {'ran': True, 'files': 5, 'bytes': 15})
        self.assertTrue(all(not p.exists() for p in remove))
        self.assertTrue(all(p.exists() for p in keep))
        later = self.file('data/later.tmp', 2)
        self.assertFalse(retention.weekly_cleanup(self.root, server.write_json)['ran'])
        self.assertTrue(later.exists())

    def test_reparse_or_link_file_and_directory_are_skipped(self):
        target = self.file('data/link.tmp', 3)
        nested = self.file('data/junction/old.tmp', 3)
        self.file('demo-link.log', 20)
        original = retention.is_plain
        def mocked(path, directory=False):
            # 用 lstat 判定的替身模拟 Windows 重解析点，不需要系统创建链接权限。
            if path.name in ('link.tmp', 'junction', 'demo-link.log'):
                return False
            return original(path, directory=directory)
        with patch.object(retention, 'is_plain', side_effect=mocked):
            result = retention.weekly_cleanup(self.root, server.write_json)
        self.assertEqual(result['files'], 0)
        self.assertTrue(target.exists())
        self.assertTrue(nested.exists())
        self.assertFalse(retention.safe_inside(self.root / 'data', self.root / 'demo-link.log'))

    def test_marker_write_failure_retries_without_touching_protected_files(self):
        self.file('data/old.tmp', 3)
        keep = self.file('data/history/keep.json', 30)
        with self.assertRaises(OSError):
            retention.weekly_cleanup(self.root, lambda *a: (_ for _ in ()).throw(OSError('写入失败')))
        self.assertTrue(keep.exists())
        self.assertTrue(retention.weekly_cleanup(self.root, server.write_json)['ran'])
