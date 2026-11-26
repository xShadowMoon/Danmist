"""隔离演示检查：临时数据、假 HTTP、8390 端口；结束后关闭服务和浏览器。"""
import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server
from round6_helpers import Http, Reply


class OfflineHttp(Http):
    def request(self, method, url, **kwargs):
        # 演示也会获取礼物配置；明确换成空表，其他外部请求一律在本机拦下。
        if method == 'GET' and url.endswith('/giftPanel/giftConfig'):
            return Reply({'code': 0, 'data': {'list': []}})
        raise server.aiohttp.ClientError('演示检查已禁用外部网络')


async def check(scratch):
    ready = asyncio.Event()
    original_start = server.web.TCPSite.start
    original_feed = server.demo_feed

    async def feed(hub):
        # 歌单页面的检查需要一首确定的假歌；演示随机消息本身不会创建待唱歌。
        hub.song_cmd('song_add', text='演示歌')
        await original_feed(hub)

    async def start(site):
        await original_start(site)
        ready.set()

    with patch.object(server.sys, 'argv', ['server.py', '--demo', '--port', '8390']), \
            patch.object(server, 'DIR', str(scratch)), \
            patch.object(server, 'demo_feed', feed), \
            patch.object(server, 'IMG_CACHE', str(scratch / 'data' / 'imgcache')), \
            patch.object(server, 'load_cookie', side_effect=AssertionError('禁止读取真实凭据')), \
            patch.object(server.aiohttp, 'ClientSession', side_effect=lambda **kwargs: OfflineHttp()), \
            patch.object(server.web.TCPSite, 'start', start):
        task = asyncio.create_task(server.main())
        waiter = asyncio.create_task(ready.wait())
        try:
            done, _ = await asyncio.wait([task, waiter], timeout=15, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                await task
            if not ready.is_set():
                raise RuntimeError('演示服务未能在 8390 启动')
            process = await asyncio.create_subprocess_exec('node', str(ROOT / 'tests' / 'check_pages.mjs'), str(scratch),
                                                           creationflags=subprocess.CREATE_NO_WINDOW,
                                                           stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            try:
                output, _ = await asyncio.wait_for(process.communicate(), 90)
                print(output.decode('utf-8', errors='replace'), end='')
                code = process.returncode
            finally:
                if process.returncode is None:
                    process.terminate()
                    await process.wait()
            if code:
                raise RuntimeError('页面检查失败：' + str(code))
        finally:
            waiter.cancel()
            task.cancel()
            await asyncio.gather(waiter, task, return_exceptions=True)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='xiaowu-pages-', dir=ROOT / 'tests') as folder:
        scratch = Path(folder)
        shutil.copytree(ROOT / 'static', scratch / 'static')
        asyncio.run(check(scratch))
    print('Demo stopped; temporary files removed.')
