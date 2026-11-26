"""事件总线（2026-11-26）：各平台的消息记下来以后发一次，订阅按顺序跑，坏一个不拖累别的。"""
import unittest

from bus import Bus
from test_backend import HubTest


class BusTests(unittest.TestCase):
    def test_order_and_isolation(self):
        b, got = Bus(), []
        b.on('dm', lambda it: got.append(('a', it['text'])))
        b.on('dm', lambda it: 1 / 0)  # 坏掉的订阅
        b.on('dm', lambda it: got.append(('c', it['text'])))
        b.on('*', lambda kind, it: got.append(('all', kind)))
        with self.assertLogs('danmaku', 'ERROR'):
            b.publish('dm', {'text': 'hi'})
        self.assertEqual(got, [('a', 'hi'), ('c', 'hi'), ('all', 'dm')])
        with self.assertRaises(ValueError):
            b.on('nope', print)


class HubBusTests(HubTest):
    def test_every_platform_message_goes_through_bus(self):
        seen = []
        self.hub.bus.on('*', lambda kind, it: seen.append((kind, it.get('plat', ''))))
        self.hub.danmaku(1, 'a', '', '你好')
        self.hub.danmaku(2, 'b', '', '斗鱼的', plat='douyu')
        self.hub.enter(3, 'c', plat='douyin')
        self.hub.gift(4, 'd', '', '小花花', 1, 0.1)
        self.hub.super_chat('s1', 5, 'e', '', 30, '加油')
        self.hub.guard_buy(6, 'f', 3, 1, 198)
        self.assertEqual(seen, [('dm', ''), ('dm', 'douyu'), ('enter', 'douyin'), ('gift', ''), ('sc', ''), ('guard', '')])


if __name__ == '__main__':
    unittest.main()
