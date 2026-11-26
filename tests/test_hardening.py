"""2026-11-26 按 Gemini 反馈加的几处：转发头不算本机、图片缓存总量上限、抖音要验证时亮黄字、换主直播间先确认、快捷方式图标。"""
import logging
import os
import struct
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

import input_validation as validation
import platforms
import server
import shortcut_icon


def png(n):
    raw = b''.join(b'\x00' + b'\xff\x00\x00\xff' * n for _ in range(n))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', n, n, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


class Req:
    def __init__(self, headers=None, remote='127.0.0.1', host='127.0.0.1:8380'):
        self.headers, self.remote, self.host = headers or {}, remote, host
        self.query, self.cookies = {}, {}


class ProxyHeaderTests(unittest.TestCase):
    def test_forwarded_requests_are_not_local(self):
        self.assertTrue(server.is_admin(Req(), '', 8380))
        for h in ('X-Forwarded-For', 'X-Real-IP', 'Forwarded', 'Via', 'X-Forwarded-Host', 'CF-Connecting-IP', 'Cf-Ray'):
            self.assertFalse(server.is_admin(Req({h: '1.2.3.4'}), '', 8380), h)


class ImgCacheTests(unittest.TestCase):
    def test_total_cap_removes_oldest(self):
        with tempfile.TemporaryDirectory() as d:
            now = time.time()
            for i in range(5):
                p = Path(d) / (f'{i:040x}' + '.webp')
                p.write_bytes(b'x' * 1000)
                os.utime(p, (now - 100 + i, now - 100 + i))
            with mock.patch.object(server, 'IMG_CACHE', d):
                server.clean_img_cache(cap=2500)
            self.assertEqual(sorted(p.name[:40] for p in Path(d).iterdir()), [f'{i:040x}' for i in (3, 4)])


class DouyinHealthTests(unittest.TestCase):
    def test_verify_and_missing_chat_warn_then_clear(self):
        d = platforms.Douyin(object(), 'douyin', '123', logging.getLogger('t'))
        try:
            d.on_item({'k': 'health', 's': 'ok'})
            self.assertFalse(d.warn)
            d.on_item({'k': 'health', 's': 'verify'})
            self.assertTrue(d.warn)
            self.assertIn('验证', d.state)
            d.on_item({'k': 'health', 's': 'ok'})
            self.assertFalse(d.warn)
            d.on_item({'k': 'health', 's': 'nodom'})
            self.assertTrue(d.warn)
        finally:
            platforms.Douyin.alive.discard(d)

    def test_debug_port_only_on_this_computer(self):
        import inspect
        src = inspect.getsource(platforms.Douyin.devtools_port)
        self.assertIn('--remote-debugging-address=127.0.0.1', src)
        self.assertNotIn('remote-allow-origins=*', src)
        self.assertTrue(any('douyincdn' in u for u in platforms.VIDEO_URLS))


class RoomSetTests(unittest.TestCase):
    def test_sure_must_be_boolean(self):
        validation.validate_command({'cmd': 'room_set', 'plat': 'bili', 'room': 373317, 'sure': True}, lambda r: r)
        validation.validate_command({'cmd': 'room_set', 'plat': 'bili', 'room': 373317}, lambda r: r)
        with self.assertRaises(validation.InputError):
            validation.validate_command({'cmd': 'room_set', 'plat': 'bili', 'room': 373317, 'sure': 'yes'}, lambda r: r)


class ShortcutIconTests(unittest.TestCase):
    def test_ico_keeps_sizes_up_to_256(self):
        ico = shortcut_icon.make_ico([png(64), png(512), png(32), png(256)])
        self.assertEqual(struct.unpack('<HHH', ico[:6]), (0, 1, 3))
        sizes = [ico[6 + 16 * i] for i in range(3)]
        self.assertEqual(sizes, [32, 64, 0])  # 256 在 .ico 里写成 0
        with self.assertRaises(ValueError):
            shortcut_icon.make_ico([png(512)])

    def test_write_ico_replaces_old_one(self):
        with tempfile.TemporaryDirectory() as d:
            for n in (32, 64):
                Path(d, f'icon-{n}.png').write_bytes(png(n))
            a = shortcut_icon.write_ico(d, (32, 64, 512), 1)
            b = shortcut_icon.write_ico(d, (32, 64, 512), 2)
            self.assertFalse(os.path.exists(a))
            self.assertTrue(os.path.exists(b))
            self.assertEqual(sorted(os.listdir(d)), ['icon-32.png', 'icon-64.png', 'mascot-2.ico'])


if __name__ == '__main__':
    unittest.main()
