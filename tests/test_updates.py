"""不联网测试「有新版本」检查：版本号比较、读 GitHub 返回、出错时不打扰。"""
import asyncio
import unittest

from aiohttp import web
import aiohttp

import updates


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updates.parse('v0.10.1'), (0, 10, 1))
        self.assertEqual(updates.parse('1.2'), (1, 2, 0))
        self.assertIsNone(updates.parse('nightly'))
        self.assertIsNone(updates.parse(None))

    def test_compares_numbers_not_text(self):
        self.assertTrue(updates.is_newer('v0.10.0', '0.9.0'))   # 按数字比：10 > 9
        self.assertTrue(updates.is_newer('v1.0.0', '0.10.3'))
        self.assertFalse(updates.is_newer('v0.10.0', '0.10.0'))
        self.assertFalse(updates.is_newer('v0.9.9', '0.10.0'))
        self.assertFalse(updates.is_newer('garbage', '0.10.0'))

    def test_current_version_is_valid(self):
        self.assertIsNotNone(updates.parse(updates.VERSION))


class FetchTests(unittest.TestCase):
    """起一个本机的假 GitHub 接口。"""

    def fetch(self, status=200, body=None):
        async def run():
            async def handler(request):
                if body is None:
                    return web.Response(status=status, text='nope')
                return web.json_response(body, status=status)
            app = web.Application()
            app.router.add_get('/latest', handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            try:
                async with aiohttp.ClientSession() as session:
                    return await updates.fetch_latest(session, f'http://127.0.0.1:{port}/latest')
            finally:
                await runner.cleanup()
        return asyncio.run(run())

    def test_reads_latest_release(self):
        info = self.fetch(body={'tag_name': 'v0.11.0', 'name': 'v0.11.0',
                                'html_url': f'https://github.com/{updates.REPO}/releases/tag/v0.11.0'})
        self.assertEqual(info['v'], '0.11.0')
        self.assertTrue(info['url'].endswith('/releases/tag/v0.11.0'))

    def test_foreign_link_replaced_with_release_page(self):
        info = self.fetch(body={'tag_name': 'v0.11.0', 'html_url': 'https://example.com/x'})
        self.assertEqual(info['url'], updates.RELEASES_PAGE)

    def test_ignores_prerelease_and_bad_tags(self):
        self.assertIsNone(self.fetch(body={'tag_name': 'v0.11.0', 'prerelease': True}))
        self.assertIsNone(self.fetch(body={'tag_name': 'latest'}))

    def test_errors_are_quiet(self):
        self.assertIsNone(self.fetch(status=403))
        self.assertIsNone(self.fetch(status=200, body=None))

    def test_unreachable_is_quiet(self):
        async def run():
            async with aiohttp.ClientSession() as session:
                return await updates.fetch_latest(session, 'http://127.0.0.1:9/latest')
        self.assertIsNone(asyncio.run(run()))


if __name__ == '__main__':
    unittest.main()
