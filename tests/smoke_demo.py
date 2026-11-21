"""仅启动本副本的 8390 演示服务，验证页面与实际 WebSocket 接线。"""
import asyncio
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import aiohttp

BASE = 'http://127.0.0.1:8390'
ORIGIN = {'Origin': BASE}
ROOT = Path(__file__).resolve().parents[1]
WS = BASE + '/ws'


async def message(ws, kind, match=lambda data: True):
    async with asyncio.timeout(8):
        while True:
            reply = await ws.receive_json()
            if reply['type'] == kind and match(reply['data']):
                return reply['data']


async def check_pages(client, child):
    for _ in range(50):
        if child.poll() is not None:
            raise RuntimeError('演示服务提前退出')
        try:
            async with client.get(BASE + '/api/ping') as response:
                if await response.text() == 'ok':
                    break
        except aiohttp.ClientConnectionError:
            pass
        await asyncio.sleep(.2)
    else:
        raise RuntimeError('演示服务未就绪')
    for path in ('/', '/obs', '/obs-songs', '/static/workbench.js', '/static/workbench.css'):
        async with client.get(BASE + path) as response:
            assert response.status == 200 and await response.read(), path
    for role in ('', '?client=obs', '?client=obs-songs'):
        async with client.ws_connect(WS + role, headers=ORIGIN) as ws:
            snap = await message(ws, 'snapshot')
            assert snap['room_id'] == 0 and snap['admin'] is (not role), role


async def check_sizes(client):
    async with client.ws_connect(WS, headers=ORIGIN) as ws:
        await message(ws, 'snapshot')
        rows = [{'name': f'回归歌曲 {i}', 'artist': '测试歌手'} for i in range(3000)]
        command = json.dumps({'cmd': 'library_import', 'rows': rows, 'rid': 'limit-import'}, ensure_ascii=False)
        command += ' ' * (3 * 1024 * 1024 - len(command.encode()))
        await ws.send_str(command)
        result = await message(ws, 'result', lambda d: d.get('rid') == 'limit-import')
        assert result['ok'], result
        await ws.send_json({'cmd': 'song_add', 'text': '歌' * 23000, 'rid': 'too-big'})
        result = await message(ws, 'result', lambda d: d.get('rid') == 'too-big')
        assert not result['ok'] and '64 KB' in result['msg'], result
        await ws.send_str(command + ' ')
        async with asyncio.timeout(8):
            async for _ in ws:
                pass
        # aiohttp 可能因尚未读完超大帧直接断开 TCP，客户端会报 1006。
        # 两种关闭方式都表示帧未进入命令分发。
        assert ws.closed and ws.close_code in (1009, 1006), ws.close_code


async def check_rate(client):
    async with client.ws_connect(WS, headers=ORIGIN) as ws:
        await message(ws, 'snapshot')
        for i in range(21):
            await ws.send_json({'cmd': 'song_move', 'id': 'missing', 'direction': 1, 'rid': f'burst-{i}'})
        responses = [await message(ws, 'result') for _ in range(21)]
        assert all('操作太快' not in r['msg'] for r in responses[:20]), responses
        assert responses[-1]['rid'] == 'burst-20' and '操作太快' in responses[-1]['msg'], responses[-1]
    async with client.ws_connect(WS, headers=ORIGIN) as ws:
        await message(ws, 'snapshot')
        await ws.send_json({'cmd': 'song_add', 'text': '未被限流的另一个连接', 'rid': 'new'})
        result = await message(ws, 'result', lambda d: d.get('rid') == 'new')
        assert result['ok'], result


async def check_public(client):
    async with client.ws_connect(WS + '?client=obs', headers=ORIGIN) as public:
        snap = await message(public, 'snapshot')
        assert not snap['admin']
        await public.send_json({'cmd': 'library_save', 'song': {'name': '不允许公开修改'}})
    async with client.ws_connect(WS, headers=ORIGIN) as admin:
        snap = await message(admin, 'snapshot')
        assert all(s['name'] != '不允许公开修改' for s in snap['library'])


async def verify(child):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as client:
        await check_pages(client, child)
        await check_sizes(client)
        await check_rate(client)
        await check_public(client)


NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def main():
    with socket.socket() as check:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):  # Windows
            check.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        check.bind(('127.0.0.1', 8390))
    # 让演示生成的假历史和日志都留在副本内的临时目录。
    with TemporaryDirectory(prefix='.demo-test-', dir=ROOT) as scratch:
        shutil.copytree(ROOT / 'static', Path(scratch) / 'static')
        bootstrap = ('import asyncio, pathlib, server, sys; '
                     'server.DIR = sys.argv.pop(1); '
                     'server.IMG_CACHE = str(pathlib.Path(server.DIR) / "data" / "imgcache"); '
                     'asyncio.run(server.main())')
        with open(Path(scratch) / 'server.log', 'w+', encoding='utf-8') as log:
            env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
            child = subprocess.Popen([sys.executable, '-B', '-c', bootstrap, scratch, '--demo', '--port', '8390'],
                                     cwd=ROOT, env=env, stdout=log, stderr=log,
                                     creationflags=NO_WINDOW)
            try:
                asyncio.run(verify(child))
                if '--browser' in sys.argv:
                    subprocess.run(['node', str(ROOT / 'tests' / 'check_pages.mjs'), scratch],
                                   cwd=ROOT, check=True, timeout=45, creationflags=NO_WINDOW)
            except BaseException:
                log.seek(0)
                print(log.read())
                raise
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=10)
    print('演示服务通过：主页 / OBS 弹幕 / OBS 歌单，3000 首批量导入、字节上限、限流与只读连接；8390 已关闭。')


if __name__ == '__main__':
    main()
