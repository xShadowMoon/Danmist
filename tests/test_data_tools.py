"""数据管理（2026-11-28）：每类多大、分类清理、两场合成一场"""
import gzip
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data_tools  # noqa: E402


def write(path, data=b'x' * 100):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


def wj(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)


def summary(sid, start, end, **kw):
    brief = {'id': sid, 'title': 't', 'start': start, 'end': end, 'total': kw.get('total', 10.0), 'income': 5.0,
             'flow': kw.get('flow', {'gift': 10.0, 'sc': 0.0, 'guard': 0.0}), 'dm_total': kw.get('dm', 3), 'user_count': kw.get('users', 2),
             'sc_count': 0, 'guard_count': 0, 'peak_online': kw.get('peak', 5), 'reason': '下播'}
    return {**brief, 'brief': brief, 'room_id': 1, 'stats': {'watched': kw.get('watched', 10)}, 'outages': [],
            'rank': kw.get('rank', []), 'scs': [], 'guards': [], 'gift_stats': kw.get('gifts', []), 'big_gifts': [],
            'viewers': kw.get('viewers', []), 'dm_log_count': kw.get('dm', 3)}


class DataToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = self.tmp.name
        self.data = os.path.join(self.app, 'data')
        write(os.path.join(self.data, 'imgcache', 'a.webp'), b'x' * 1000)
        write(os.path.join(self.data, 'webview', 'EBWebView', 'Default', 'Cache', 'Cache_Data', 'f1'), b'x' * 2000)
        write(os.path.join(self.data, 'webview', 'EBWebView', 'Default', 'Local Storage', 'leveldb', 'keep.ldb'), b'x' * 300)
        for i in range(5):
            p = os.path.join(self.app, '备份', '数据', f'data-2026112{i}.zip')
            write(p, b'x' * 500)
            os.utime(p, (time.time() - (10 - i) * 86400,) * 2)
        self.h = os.path.join(self.data, 'history', '1')
        old, new = '20200101-1200', '20261128-1200-abcdefabcdef'
        wj(os.path.join(self.h, old + '.json'), summary(old, 1577851200, 1577854800))
        write(os.path.join(self.h, old + '.dm.jsonl'), b'{"t":1}\n' * 10)
        wj(os.path.join(self.h, new + '.json'), summary(new, int(time.time()) - 60, int(time.time())))
        write(os.path.join(self.h, new + '.dm.jsonl'), b'{"t":2}\n' * 10)

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        return {r['key']: r for r in data_tools.report(self.app)}

    def test_report(self):
        r = self.rows()
        self.assertEqual(r['img']['bytes'], 1000)
        self.assertEqual(r['browser']['bytes'], 2000)  # 登录信息（Local Storage）不算缓存
        self.assertEqual((r['backup']['bytes'], r['backup']['files']), (2500, 5))
        self.assertEqual(r['dm']['files'], 2)
        self.assertGreater(r['total']['bytes'], 5000)

    def test_clean_keeps_logins_and_new(self):
        data_tools.clean(self.app, 'browser')
        self.assertFalse(os.path.exists(os.path.join(self.data, 'webview', 'EBWebView', 'Default', 'Cache', 'Cache_Data', 'f1')))
        self.assertTrue(os.path.exists(os.path.join(self.data, 'webview', 'EBWebView', 'Default', 'Local Storage', 'leveldb', 'keep.ldb')))
        data_tools.clean(self.app, 'img')
        self.assertEqual(self.rows()['img']['bytes'], 0)
        data_tools.clean(self.app, 'backup', keep=2)
        _, names = data_tools.backups(self.app)
        self.assertEqual(names, ['data-20261124.zip', 'data-20261123.zip'])  # 最近的两份
        data_tools.clean(self.app, 'dm', days=90)
        self.assertFalse(os.path.exists(os.path.join(self.h, '20200101-1200.dm.jsonl')))
        self.assertTrue(os.path.exists(os.path.join(self.h, '20200101-1200.json')))  # 那场的数字还在
        self.assertTrue(os.path.exists(os.path.join(self.h, '20261128-1200-abcdefabcdef.dm.jsonl')))
        with self.assertRaises(ValueError):
            data_tools.clean(self.app, 'history')

    def test_clean_protects_current(self):
        data_tools.clean(self.app, 'dm', days=0, protect=('20261128-1200-abcdefabcdef',))
        self.assertTrue(os.path.exists(os.path.join(self.h, '20261128-1200-abcdefabcdef.dm.jsonl')))

    def test_merge_sessions(self):
        a, b = '20261127-2000-111111111111', '20261127-2030-222222222222'
        wj(os.path.join(self.h, a + '.json'), summary(a, 1000, 2000, total=10.0, dm=2, users=2, peak=5,
                                                      viewers=[[1, '甲', 1, 5.0, 1], [2, '乙', 1, 0, 1]],
                                                      rank=[{'uid': 1, 'name': '甲', 'face': '', 'spend': 5.0, 'guard': 0, 'dm': 1}],
                                                      gifts=[{'name': '小心心', 'num': 2, 'yuan': 0.2}]))
        wj(os.path.join(self.h, b + '.json'), summary(b, 2100, 3000, total=6.0, dm=3, users=2, peak=9,
                                                      flow={'gift': 6.0, 'sc': 0.0, 'guard': 0.0},
                                                      viewers=[[1, '甲改名', 2, 1.0, 1], [3, '丙', 1, 5.0, 1]],
                                                      rank=[{'uid': 1, 'name': '甲改名', 'face': '', 'spend': 1.0, 'guard': 0, 'dm': 2}],
                                                      gifts=[{'name': '小心心', 'num': 3, 'yuan': 0.3}]))
        with gzip.open(os.path.join(self.h, a + '.dm.jsonl.gz'), 'wt', encoding='utf-8') as f:
            f.write('{"t":1,"text":"a"}\n')
        write(os.path.join(self.h, b + '.dm.jsonl'), '{"t":2,"text":"b"}\n'.encode())
        wj(os.path.join(self.h, 'index.json'), [summary(a, 1000, 2000)['brief'], summary(b, 2100, 3000)['brief']])

        def writer(path, obj):
            wj(path, obj)
        m = data_tools.merge_sessions(self.h, b, a, writer)  # 顺序反着给也是留先开始的那场
        self.assertEqual(m['id'], a)
        self.assertEqual((m['start'], m['end'], m['total'], m['dm_total'], m['peak_online']), (1000, 3000, 16.0, 5, 9))
        self.assertEqual(m['user_count'], 3)  # 甲两场都来了，算一个人
        v = {x[0]: x for x in m['viewers']}
        self.assertEqual(v[1], [1, '甲改名', 3, 6.0, 2])
        self.assertEqual(m['rank'][0]['spend'], 6.0)
        self.assertEqual(m['gift_stats'][0]['num'], 5)
        self.assertFalse(os.path.exists(os.path.join(self.h, b + '.json')))
        self.assertFalse(os.path.exists(os.path.join(self.h, a + '.dm.jsonl.gz')))
        self.assertEqual([r['text'] for r in data_tools.read_dm(self.h, a)], ['a', 'b'])
        with open(os.path.join(self.h, 'index.json'), encoding='utf-8') as f:
            idx = json.load(f)
        self.assertEqual([x['id'] for x in idx], [a])
        with self.assertRaises(ValueError):
            data_tools.merge_sessions(self.h, a, a, writer)


if __name__ == '__main__':
    unittest.main()
