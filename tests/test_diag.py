"""导出诊断信息（2026-11-26）：密钥和 IP 不能漏出去。"""
import unittest

import server


class DiagTests(unittest.TestCase):
    def test_secrets_hidden(self):
        out = server.redact({'discord_webhook': 'https://discord.com/api/webhooks/1/abc', 'room': 1,
                             'ai_voice': {'url': 'http://127.0.0.1:9880', 'api_key': 'k'}, 'admin_key': '', 'login_file': 'a.json'})
        self.assertEqual(out['discord_webhook'], '***')
        self.assertEqual(out['ai_voice'], {'url': 'http://127.0.0.1:9880', 'api_key': '***'})
        self.assertEqual(out['admin_key'], '')  # 空的不用藏
        self.assertEqual((out['room'], out['login_file']), (1, 'a.json'))

    def test_log_lines_masked(self):
        line = server.mask_line('打开了 203.0.113.45，cookie SESSDATA=abc123; bili_jct=zz MUSIC_U=qq')
        self.assertNotIn('113', line)
        for secret in ('abc123', 'zz', 'qq'):
            self.assertNotIn('=' + secret, line)


if __name__ == '__main__':
    unittest.main()
