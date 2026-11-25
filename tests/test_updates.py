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


class ApplyTests(unittest.TestCase):
    def test_apply_keeps_settings_and_data(self):
        import os, tempfile
        with tempfile.TemporaryDirectory() as app:
            for name, text in (('server.py', 'old'), ('config.json', 'mine'), ('start.bat', 'old bat')):
                with open(os.path.join(app, name), 'w', encoding='utf-8') as f:
                    f.write(text)
            os.makedirs(os.path.join(app, 'data'))
            with open(os.path.join(app, 'data', 'keep.json'), 'w', encoding='utf-8') as f:
                f.write('x')
            new = os.path.join(updates.update_dir(app), 'v9.9.9', 'pkg')
            os.makedirs(os.path.join(new, 'static'))
            for name, text in (('server.py', 'new'), ('config.json', 'theirs'), ('start.bat', 'new bat'), ('static/a.js', 'js')):
                with open(os.path.join(new, name), 'w', encoding='utf-8') as f:
                    f.write(text)
            with open(os.path.join(updates.update_dir(app), 'ready.txt'), 'w', encoding='utf-8') as f:
                f.write('9.9.9\n' + new + '\n')
            self.assertEqual(updates.staged(app)[0], '9.9.9')
            self.assertEqual(updates.apply(app, say=lambda t: None, later=('start.bat',)), '9.9.9')
            read = lambda *p: open(os.path.join(app, *p), encoding='utf-8').read()
            self.assertEqual(read('server.py'), 'new')
            self.assertEqual(read('config.json'), 'mine')
            self.assertEqual(read('data', 'keep.json'), 'x')
            self.assertEqual(read('static', 'a.js'), 'js')
            self.assertEqual(read('start.bat'), 'old bat')
            self.assertEqual(read('start.bat.new'), 'new bat')
            self.assertEqual(updates.staged(app), (None, None))


if __name__ == '__main__':
    unittest.main()
