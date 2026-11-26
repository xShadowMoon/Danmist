"""雾幕自己的窗口（2026-11-26）：记住窗口大小位置、第一次从 Edge 窗口搬设置过来。窗口本身要有桌面才能开，这里不开。"""
import json
import os
import tempfile
import unittest
from unittest import mock

import native_window as nw


class StateTests(unittest.TestCase):
    def test_state_roundtrip_and_limits(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(nw, 'STATE', os.path.join(d, 'w.json')), mock.patch.object(nw, 'DATA', d):
                self.assertEqual(nw.load_state(), {'width': 1400, 'height': 900, 'x': None, 'y': None})
                win = mock.Mock(width=1600, height=1000, x=40, y=30)
                nw.save_state(win)
                self.assertEqual(nw.load_state(), {'width': 1600, 'height': 1000, 'x': 40, 'y': 30})
                nw.save_state(mock.Mock(width=160, height=30, x=-32000, y=-32000))  # 最小化时关的不记
                self.assertEqual(nw.load_state()['width'], 1600)
                json.dump({'w': 100, 'h': 99999, 'x': 'a'}, open(os.path.join(d, 'w.json'), 'w'))
                self.assertEqual(nw.load_state(), {'width': 900, 'height': 4320, 'x': None, 'y': None})

    def test_carry_over_settings_from_edge_window_once(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.path.join(d, 'desktop-browser', 'Default', 'Local Storage', 'leveldb')
            os.makedirs(old)
            open(os.path.join(old, '000003.log'), 'w').write('x')
            open(os.path.join(old, 'LOCK'), 'w').write('')
            with mock.patch.object(nw, 'DATA', d), mock.patch.object(nw, 'STORE', os.path.join(d, 'webview')):
                nw.carry_over_storage()
                new = os.path.join(d, 'webview', 'EBWebView', 'Default', 'Local Storage', 'leveldb')
                self.assertTrue(os.path.isfile(os.path.join(new, '000003.log')))
                self.assertFalse(os.path.exists(os.path.join(new, 'LOCK')))
                open(os.path.join(old, '000003.log'), 'w').write('changed')
                nw.carry_over_storage()  # 已经有了就不再覆盖
                self.assertEqual(open(os.path.join(new, '000003.log')).read(), 'x')


if __name__ == '__main__':
    unittest.main()
