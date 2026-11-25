import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import platforms  # noqa: E402


class Hub:
    def __init__(self):
        self.ev = []

    def danmaku(self, uid, name, face, text, **k):
        self.ev.append(('dm', uid, name, text, k.get('plat')))

    def gift(self, uid, name, face, gift, num, yuan, img='', **k):
        self.ev.append(('gift', uid, name, gift, num, yuan, k.get('plat')))

    def enter(self, uid, name, face, kind, guard, **k):
        self.ev.append(('enter', uid, name, k.get('plat')))


class PlatformTests(unittest.TestCase):
    def test_rooms_are_cleaned(self):
        rows = platforms.clean_rooms([{'plat': 'douyu', 'room': ' 9999 '}, {'plat': 'huya', 'room': 'abc333003'}, {'plat': 'douyu', 'room': '9999'}])
        self.assertEqual(rows, [{'plat': 'douyu', 'room': '9999', 'on': True}, {'plat': 'huya', 'room': '333003', 'on': True}])
        for bad in ([{'plat': 'kuaishou', 'room': '1'}], [{'plat': 'douyu', 'room': 'x'}], [{'plat': 'douyu', 'room': str(i)} for i in range(1, 9)]):
            with self.assertRaises(ValueError):
                platforms.clean_rooms(bad)

    def test_uids_never_clash_with_bilibili(self):
        self.assertEqual(platforms.puid('douyu', 123), 10 ** 14 + 123)
        self.assertEqual(platforms.puid('huya', 1199531641790), 2 * 10 ** 14 + 1199531641790)

    def test_douyu_messages(self):
        h = Hub()
        src = platforms.Douyu(h, 'douyu', '9999', None)
        src.gift_names = {'824': ('粉丝荧光棒', 0.0, '')}
        src.handle(platforms._dy_parse('type@=chatmsg/uid@=5/nn@=小明@S/txt@=你好@A/ic@=avatar@Sx/bnn@=牌/bl@=3/'))
        src.handle(platforms._dy_parse('type@=dgb/uid@=5/nn@=小明/gfid@=824/gfcnt@=10/'))
        src.handle(platforms._dy_parse('type@=dgb/uid@=5/nn@=小明/gfid@=0/'))
        src.handle(platforms._dy_parse('type@=uenter/uid@=6/nn@=小红/'))
        self.assertEqual(h.ev[0], ('dm', 10 ** 14 + 5, '小明/', '你好@', 'douyu'))
        self.assertEqual(h.ev[1][:5], ('gift', 10 ** 14 + 5, '小明', '粉丝荧光棒', 10))
        self.assertEqual(len(h.ev), 3)
        self.assertEqual(h.ev[2][0], 'enter')

    def test_tars_roundtrip(self):
        w = platforms._TW().int(0, 1400).str(1, '弹幕').int(2, 2 ** 40).bytes(3, b'\x01\x02').strlist(4, ['a', 'b'])
        d, _ = platforms.tars_read(bytes(w.b))
        self.assertEqual(d, {0: 1400, 1: '弹幕', 2: 2 ** 40, 3: b'\x01\x02', 4: ['a', 'b']})


if __name__ == '__main__':
    unittest.main()
