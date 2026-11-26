"""外部服务连续失败先歇一会（2026-11-26）。"""
import unittest

from breaker import Breaker, Resting


class BreakerTests(unittest.TestCase):
    def test_rests_after_failures_and_backs_off(self):
        now = [100.0]
        b = Breaker('测试服务', fails=3, rest=30, max_rest=100, clock=lambda: now[0])
        b.fail(); b.fail()
        self.assertTrue(b.ready())
        b.fail()  # 第 3 次：歇 30 秒
        self.assertFalse(b.ready())
        with self.assertRaises(Resting):
            b.check()
        now[0] += 31
        self.assertTrue(b.ready())
        for _ in range(3):
            b.fail()
        self.assertEqual(b.left(), 60)  # 又失败：歇更久
        now[0] += 61
        for _ in range(6):
            b.fail()
            now[0] += 200
        self.assertLessEqual(b.rest, 100)  # 最多歇 max_rest
        b.ok()
        self.assertEqual((b.n, b.rest), (0, 30))  # 一成功马上恢复


if __name__ == '__main__':
    unittest.main()
