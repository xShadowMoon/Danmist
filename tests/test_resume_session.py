"""断流 5 分钟内重开算同一场（2026-11-23）。"""
import asyncio
import datetime
from types import SimpleNamespace
from unittest.mock import patch

import server
from test_backend import HubTest, run_without_io


def poll_once(hub, start, now, live=1):
    class RoomReply:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def json(self, **kwargs):
            return {'data': {'live_status': live, 'title': '测试直播', 'live_time': datetime.datetime.fromtimestamp(
                start, server.BJ).strftime('%Y-%m-%d %H:%M:%S') if live else '0000-00-00 00:00:00'}}

    async def stop_after_one_poll(waiting, timeout):
        waiting.close()
        raise asyncio.CancelledError

    session = SimpleNamespace(get=lambda *args, **kwargs: RoomReply())
    with patch.object(server.time, 'time', return_value=now), \
            patch.object(server.asyncio, 'wait_for', side_effect=stop_after_one_poll):
        try:
            run_without_io(server.poll_room(hub, session, 123))
        except asyncio.CancelledError:
            pass


class ResumeTests(HubTest):
    def open_broadcast(self):
        t0 = self.state.session_start
        poll_once(self.hub, t0, t0 + 5)          # 第一次查到开播
        self.hub.danmaku(1, '观众甲', '', '前半段')
        self.hub.gift(1, '观众甲', '', '礼物', 1, 10)
        return t0

    def test_short_break_after_preparing_is_same_session(self):
        t0 = self.open_broadcast()
        aid = self.state.archive_id
        server.Handler(self.hub).handle(None, {'cmd': 'PREPARING'})   # 断流，先存一份
        self.assertTrue(self.state.summarized)
        settled = self.state.settled_at
        self.hub.gift(2, '观众乙', '', '断流时送的', 1, 5)            # 断流期间：标「下播」
        self.assertEqual(self.state.gifts[-1].get('source'), '下播')
        restart = settled + 120
        poll_once(self.hub, restart, restart + 3)
        self.assertEqual(self.state.archive_id, aid)
        self.assertFalse(self.state.summarized)
        self.assertEqual(self.state.live_start, t0)
        self.assertEqual(self.state.live_merged, [restart])
        self.assertNotIn('source', self.state.gifts[-1])
        self.assertEqual(self.state.snapshot()['live_from'], t0)
        self.hub.danmaku(3, '观众丙', '', '后半段')
        self.hub.gift(3, '观众丙', '', '礼物', 1, 20)
        # 之后每分钟的查询拿到的都是重开的时间，不能再被当成新的一场
        poll_once(self.hub, restart, restart + 70)
        poll_once(self.hub, restart, restart + 130)
        self.assertEqual(self.state.archive_id, aid)
        server.Handler(self.hub).handle(None, {'cmd': 'PREPARING'})   # 真下播
        rows = [b for b in self.history.list() if b['id'] == aid]
        self.assertEqual(len(rows), 1)                                  # 只有一条，覆盖了断流时那份
        saved = self.history.get(aid)
        self.assertEqual(saved['start'], t0)
        self.assertEqual(saved['total'], 35)
        self.assertEqual([d['text'] for d in self.history.dm(aid)], ['前半段', '后半段'])

    def test_break_too_short_to_see_offline(self):
        t0 = self.open_broadcast()
        aid = self.state.archive_id
        poll_once(self.hub, t0, t0 + 600)        # 一直在播
        restart = t0 + 630                       # 断了 30 秒，PREPARING 没来，查询也没赶上
        poll_once(self.hub, restart, restart + 10)
        self.assertEqual(self.state.archive_id, aid)
        self.assertEqual(self.state.live_start, t0)
        self.assertEqual(self.history.list(), [])

    def test_long_break_is_new_session(self):
        t0 = self.open_broadcast()
        aid = self.state.archive_id
        server.Handler(self.hub).handle(None, {'cmd': 'PREPARING'})
        restart = self.state.settled_at + 600
        poll_once(self.hub, restart, restart + 3)
        self.assertNotEqual(self.state.archive_id, aid)
        self.assertEqual(self.state.live_start, restart)
        self.assertEqual(self.state.live_merged, [])

    def test_merged_starts_survive_restart(self):
        self.open_broadcast()
        server.Handler(self.hub).handle(None, {'cmd': 'PREPARING'})
        restart = self.state.settled_at + 60
        poll_once(self.hub, restart, restart + 3)
        self.assertNotEqual(self.state.save(), False)
        again = server.State(123)
        self.assertEqual(again.live_merged, [restart])
        self.assertEqual(again.archive_id, self.state.archive_id)


if __name__ == '__main__':
    import unittest
    unittest.main()
