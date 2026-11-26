"""断线用假的连接状态和响应测试，不访问 B 站。"""
import logging
import asyncio
from unittest.mock import patch

import server
import connection_recovery as recovery
from test_backend import HubTest


class RecoveryTests(HubTest):
    def start(self):
        self.state.live_start = self.state.session_start
        self.hub.room_update(live=1, room_real=123)
        self.hub.bili_seen = self.state.session_start
        return self.state.session_start

    def test_gap_persists_recovers_and_archives(self):
        now = self.start()
        recovery.connection_state(self.hub, False, now + 80)
        recovery.connection_state(self.hub, False, now + 90)
        self.assertEqual(len(self.state.outages), 1)
        self.state.save()
        again = server.State(123)
        self.assertIsNone(again.outages[0]['up_at'])
        recovery.connection_state(self.hub, True, now + 100)
        self.assertTrue(self.hub.wake.is_set())
        self.assertTrue(self.hub.guard_wake.is_set())
        self.assertTrue(self.hub.recover_wake.is_set())
        self.assertEqual(self.state.room['up_at'], now + 100)
        self.hub.danmaku(1, '观众', '', '恢复了')
        self.hub.close_broadcast('下播')
        self.assertEqual(self.history.get(self.state.archive_id)['outages'], self.state.outages)
        self.assertNotIn('outages', self.state.room)
        self.assertEqual(self.state.snapshot()['outages'], self.state.outages)

    def test_gap_cap_and_local_edits_during_outage(self):
        now = self.start()
        for i in range(205):
            self.hub.bili_seen = now + i * 100
            recovery.connection_state(self.hub, False, now + i * 100 + 80)
            recovery.connection_state(self.hub, True, now + i * 100 + 90)
        self.assertEqual(len(self.state.outages), 200)
        recovery.connection_state(self.hub, False, now + 30000)
        self.hub.song_cmd('song_add', text='断网时点的歌')
        self.hub.notes.set(1, '观众', '断网也能记')
        self.assertIsNot(self.state.save(), False)
        self.assertTrue(self.hub.dmlog.flush())
        self.assertEqual(server.State(123).songs[0]['name'], '断网时点的歌')
        self.assertEqual(server.Notes().data['1']['note'], '断网也能记')

    def test_recovered_sc_dedup_live_and_reload_and_foreign_session(self):
        now = self.start()
        gap = {'down_at': now, 'up_at': now + 100}
        row = {'id': 45, 'uid': 1, 'price': 30, 'start_time': now + 30, 'end_time': now + 120,
               'message': '补录测试', 'user_info': {'uname': '观众', 'face': '', 'guard_level': 0}}
        data = {'room_info': {'room_id': 123, 'live_start_time': now}, 'watched_show': {'num': 100},
                'like_info_v3': {'total_likes': 50}, 'super_chat_info': {'message_list': [row]}}
        self.assertEqual(recovery.apply_recovery(self.hub, data, gap), 1)
        self.assertEqual(recovery.apply_recovery(self.hub, data, gap), 0)
        self.hub.super_chat('45', 1, '观众', '', 30, '重复实时推送')
        self.assertEqual(self.state.flow['sc'], 30)
        self.assertTrue(self.state.scs[0]['recovered'])
        self.assertEqual(self.state.scs[0]['t'], now + 30)
        self.assertEqual(self.state.stats['watched'], 100)
        self.assertEqual(self.state.stats['likes'], 50)
        self.state.save()
        again = server.Hub(server.State(123), self.history)
        again.emit = lambda *a, **k: None
        again.state.room['room_real'] = 123
        self.assertEqual(recovery.apply_recovery(again, data, gap), 0)
        data['room_info']['live_start_time'] = now + 200
        with self.assertRaises(ValueError):
            recovery.apply_recovery(self.hub, data, gap)
        self.assertEqual(self.state.flow['sc'], 30)

    def test_reconnect_delays_and_repeated_log_filter(self):
        delays = [recovery.retry_delay(i) for i in range(1, 20)]
        self.assertEqual(delays, sorted(delays))
        self.assertGreaterEqual(min(delays), 5)
        self.assertLessEqual(max(delays), 60)
        filt = recovery.RepeatFilter()
        record = logging.LogRecord('blivedm', logging.WARNING, 'network.py', 10, '网络失败', (), None)
        with patch('connection_recovery.time.monotonic', return_value=100):
            self.assertTrue(filt.filter(record))
            self.assertFalse(filt.filter(record))
        with patch('connection_recovery.time.monotonic', return_value=160):
            self.assertTrue(filt.filter(record))

    def test_short_transport_disconnect_and_first_packet_recovery(self):
        now = self.start()
        client = object.__new__(server.TrackedClient)
        client.hub = self.hub
        client._heartbeat_timer_handle = None
        with patch.object(server.time, 'time', return_value=now + 5):
            asyncio.run(client._on_ws_close())
        self.assertFalse(self.state.room['bili_ok'])
        with patch.object(server.time, 'time', return_value=now + 7), patch.object(server.blivedm.BaseHandler, 'handle'):
            server.Handler(self.hub).handle(None, {'cmd': 'HEARTBEAT'})
        self.assertEqual(self.state.outages[-1]['up_at'], now + 7)
        self.hub.stopping = True
        asyncio.run(client._on_ws_close())
        self.assertEqual(len(self.state.outages), 1)
        self.assertTrue(self.state.room['bili_ok'])

    def test_variable_retry_counts_do_not_flood_log_output(self):
        filt = recovery.RepeatFilter()
        with patch('connection_recovery.time.monotonic', return_value=100):
            for count in range(10):
                row = logging.LogRecord('blivedm', logging.WARNING, 'network.py', 10, 'retry_count=%d', (count,), None)
                self.assertEqual(filt.filter(row), count == 0)

    def test_bad_sc_container_is_retryable_validation_error(self):
        now = self.start()
        gap = {'down_at': now, 'up_at': now + 100}
        for bad in ([1], 'broken', 1, False):
            data = {'room_info': {'room_id': 123, 'live_start_time': now}, 'super_chat_info': bad}
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                recovery.apply_recovery(self.hub, data, gap)
        self.assertEqual(self.state.flow['sc'], 0)
        self.assertNotIn('recovery', gap)
