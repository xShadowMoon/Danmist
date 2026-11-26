import unittest
from types import SimpleNamespace
from unittest.mock import patch
from public_limits import PublicLimits, client_ip


class PublicLimitTests(unittest.TestCase):
    def test_total_ip_release_and_abnormal_cleanup(self):
        limits = PublicLimits(total=3, per_ip=2)
        self.assertFalse(limits.reserve('a', 'ip1'))
        self.assertFalse(limits.reserve('b', 'ip1'))
        self.assertTrue(limits.reserve('c', 'ip1'))
        self.assertFalse(limits.reserve('c', 'ip2'))
        self.assertTrue(limits.reserve('d', 'ip3'))
        limits.release('a')
        limits.release('a')
        self.assertFalse(limits.reserve('d', 'ip3'))
        self.assertEqual(limits.snapshot()['public'], 3)

    def test_connection_frequency_and_window_expiry(self):
        limits = PublicLimits(connect_rate=2)
        for n in range(2):
            self.assertFalse(limits.reserve(n, 'ip', now=100))
            limits.release(n)
        self.assertTrue(limits.reserve(3, 'ip', now=159))
        self.assertFalse(limits.reserve(3, 'ip', now=160))

    def test_http_gequ_ping_and_admin_independent(self):
        limits = PublicLimits(http_rate=2, gequ_rate=5)
        self.assertFalse(limits.http('ip', '/', now=100))
        self.assertFalse(limits.http('ip', '/static/app.js', now=100))
        self.assertTrue(limits.http('ip', '/img', now=100))
        for _ in range(5):
            self.assertFalse(limits.http('ip', '/gequ.json', now=100))
            self.assertFalse(limits.http('ip', '/api/ping', now=100))
            self.assertFalse(limits.http('ip', '/', exempt=True, now=100))
        self.assertTrue(limits.http('ip', '/gequ.html', now=100))

    def test_obs_separate_caps_and_admin_preview_exempt(self):
        limits = PublicLimits(total=1, per_ip=1, obs_total=2, obs_ip=1)
        self.assertFalse(limits.reserve('v', 'ip'))
        self.assertFalse(limits.reserve('o', 'ip', 'obs'))
        self.assertTrue(limits.reserve('o2', 'ip', 'obs'))
        self.assertFalse(limits.reserve('o2', 'ip2', 'obs'))
        self.assertTrue(limits.reserve('o3', 'ip3', 'obs'))
        self.assertFalse(limits.reserve('admin-preview', 'ip', exempt=True))
        self.assertEqual(limits.snapshot()['public'], 1)

    def test_proxy_header_is_only_used_on_trusted_local_tunnel(self):
        req = SimpleNamespace(remote='203.0.113.1', host='live.shadowcary.com',
                              headers={'CF-Connecting-IP': '198.51.100.8', 'Cf-Ray': 'fake'})
        self.assertEqual(client_ip(req, 'https://live.shadowcary.com'), '203.0.113.1')
        req.remote = '127.0.0.1'
        req.host = '127.0.0.1:8390'
        self.assertEqual(client_ip(req, 'https://live.shadowcary.com'), '127.0.0.1')
        req.host = 'live.shadowcary.com'
        self.assertEqual(client_ip(req, 'https://live.shadowcary.com'), '198.51.100.8')
        req.headers['CF-Connecting-IP'] = 'nonsense'
        self.assertEqual(client_ip(req, 'https://live.shadowcary.com'), '127.0.0.1')

    def test_memory_bound_and_rejected_logs_aggregate(self):
        limits = PublicLimits(max_ips=2)
        limits.http('a', '/', now=100)
        limits.http('b', '/', now=100)
        for n in range(1000):
            self.assertTrue(limits.http(str(n), '/', now=101))
        self.assertEqual(len(limits.windows), 2)
        with patch('public_limits.log.warning') as logged:
            limits.report(120)
            limits.report(121)
            self.assertEqual(logged.call_count, 1)
            self.assertEqual(logged.call_args.kwargs['extra']['error_count'], 1000)
        limits.report(160)
        self.assertEqual(len(limits.windows), 0)

    def test_minute_boundary_does_not_reset_recent_burst(self):
        limits = PublicLimits(http_rate=3)
        self.assertFalse(limits.http('ip', '/', now=100))
        self.assertFalse(limits.http('ip', '/', now=159))
        self.assertFalse(limits.http('ip', '/', now=159.1))
        self.assertFalse(limits.http('ip', '/', now=160))
        self.assertTrue(limits.http('ip', '/', now=160.1))

    def test_rejection_counts_enter_error_journal_as_one_kind(self):
        import logging
        from error_journal import ErrorJournal
        journal = ErrorJournal(None, None, lambda *a: None)
        for count in (100, 250):
            record = logging.LogRecord('xiaowu', logging.WARNING, 'public_limits.py', 42,
                                       '公开访问已限制：%s', ('访问太频繁',), None)
            record.error_count = count
            journal.emit(record)
        self.assertEqual(len(journal.rows), 1)
        self.assertEqual(journal.rows[0]['count'], 350)
