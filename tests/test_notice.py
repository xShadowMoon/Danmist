import asyncio
import unittest

import server


class NoticeTests(unittest.TestCase):
    """B 站的活动 / 系统横幅（COMMON_NOTICE_DANMAKU）当成一条 kind=notice 的弹幕（2026-11-23）。"""
    def setUp(self):
        self.addCleanup(asyncio.set_event_loop, None)
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        asyncio.set_event_loop(self.loop)
        self.state = server.State(1)
        self.state.file = None
        self.hub = server.Hub(self.state, server.History(1), persist=False)
        self.h = server.Handler(self.hub)

    def notice(self, segs):
        self.h.handle(None, {'cmd': 'COMMON_NOTICE_DANMAKU', 'data': {'content_segments': segs}})

    def test_text_and_link(self):
        self.notice([{'type': 1, 'text': '逃离鸭科夫：雾冬Hanaki 未能抵御第 1 级风暴，基地等级不变 '},
                     {'type': 1, 'text': '查看活动>>', 'link': 'https://live.bilibili.com/activity'}])
        d = self.state.dm[-1]
        self.assertEqual(d['kind'], 'notice')
        self.assertEqual(d['text'], '逃离鸭科夫：雾冬Hanaki 未能抵御第 1 级风暴，基地等级不变')
        self.assertEqual(d['link'], 'https://live.bilibili.com/activity')
        self.assertEqual(server.viewer_view('dm', d)['kind'], 'notice')  # 普通链接也看得到

    def test_same_notice_once_a_minute(self):
        for _ in range(3):
            self.notice([{'text': '同一条横幅'}])
        self.assertEqual(sum(1 for d in self.state.dm if d.get('kind') == 'notice'), 1)

    def test_bad_input_ignored(self):
        self.h.handle(None, {'cmd': 'COMMON_NOTICE_DANMAKU', 'data': {'content_segments': 'x'}})
        self.h.handle(None, {'cmd': 'COMMON_NOTICE_DANMAKU', 'data': {}})
        self.assertFalse(any(d.get('kind') == 'notice' for d in self.state.dm))


if __name__ == '__main__':
    unittest.main()
