"""下播期间送的礼物 / 开的舰长：标「下播」，新开播清零时留到下一场（2026-11-18）。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class OfflineGiftTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='xiaowu-tests-', dir=Path(__file__).resolve().parent)
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.object(server, 'DIR', directory.name))
        self.state = server.State(123)
        self.hub = server.Hub(self.state, server.History(123))
        self.hub.emit = lambda *a, **k: None

    def test_offline_items_marked_and_carried(self):
        s = self.state
        s.room['live'] = 1
        self.hub.gift(1, '直播时', '', '小花花', 1, 0.1)
        s.room['live'] = 0
        self.hub.gift(2, '下播后', '', '告白花束', 1, 19.9)
        self.hub.guard_buy(3, '下播上舰', 3, 1, 198)
        self.assertNotIn('source', s.gifts[0])
        self.assertEqual(s.gifts[1]['source'], '下播')
        self.assertEqual(s.guards[0]['source'], '下播')
        self.hub.new_session('自动结算')
        self.assertEqual([g['name'] for g in s.gifts], ['下播后'])
        self.assertEqual([g['name'] for g in s.guards], ['下播上舰'])
        self.assertEqual(s.flow['gift'], 0)  # 钱不算进新一场

    def test_manual_reset_clears_everything(self):
        s = self.state
        s.room['live'] = 0
        self.hub.gift(2, '下播后', '', '告白花束', 1, 19.9)
        self.hub.new_session('手动清零')
        self.assertEqual(s.gifts, [])


if __name__ == '__main__':
    unittest.main()
