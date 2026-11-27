"""点歌姬登录音乐账号（2026-11-26）：弹出一个真的浏览器窗口，打开网易云 / QQ 音乐官网的登录页。

以前用接口生成二维码登录，扫完确认后常被平台拦下（风控不让第三方程序扫码登录），一直登不上。
现在走官网自己的登录流程：主播在弹出来的窗口里像平常一样登录（扫码、密码都行），
雾幕从这个窗口读到登录信息（Cookie），交给 music.py 的 set_cookie 核对，然后把窗口关掉。

窗口用单独的配置文件夹 data/music-browser，不碰平时的浏览器；只开在本机的调试口（127.0.0.1）。
"""
import asyncio
import json
import os
import subprocess

import aiohttp

from platforms import find_browser

PAGES = {'163': 'https://music.163.com/#/login', 'qq': 'https://y.qq.com/'}
NEED = {'163': ('MUSIC_U',), 'qq': ('qqmusic_key', 'qm_keyst')}
WAIT = 300  # 最多等 5 分钟


def cookie_text(src, cookies):
    """从浏览器的 Cookie 里挑出登录要的那几个，拼成一段"""
    jar = {}
    for c in cookies:
        dom = str(c.get('domain') or '')
        if (src == '163' and dom.endswith('163.com')) or (src == 'qq' and dom.endswith('qq.com')):
            jar[str(c.get('name'))] = str(c.get('value') or '')
    if src == '163':
        if not jar.get('MUSIC_U'):
            return ''
        return '; '.join(f'{k}={jar[k]}' for k in ('MUSIC_U', '__csrf') if jar.get(k))
    key = jar.get('qqmusic_key') or jar.get('qm_keyst')
    uin = jar.get('uin') or jar.get('qqmusic_uin') or jar.get('wxuin')
    if not key or not uin:
        return ''
    return f'uin={uin}; qqmusic_key={key}'


async def web_login(src, data_dir, check, log, timeout=WAIT):
    """开窗口等登录。check(src, cookie) 是 music.set_cookie，返回 (ok, msg)。返回 (ok, msg)"""
    exe = find_browser()
    if not exe:
        return False, '没找到 Edge / Chrome，用「粘贴登录信息」吧'
    prof = os.path.join(data_dir, 'music-browser')
    os.makedirs(prof, exist_ok=True)
    port_file = os.path.join(prof, 'DevToolsActivePort')
    try:
        os.remove(port_file)
    except OSError:
        pass
    args = [exe, '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1', '--remote-allow-origins=http://127.0.0.1',
            f'--user-data-dir={prof}', '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-sync',
            '--disable-features=msImplicitSignin', '--window-size=1100,800', '--new-window', PAGES[src]]
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=0x08000000 if os.name == 'nt' else 0)
    try:
        async with aiohttp.ClientSession() as s:
            port = 0
            for _ in range(100):
                await asyncio.sleep(0.2)
                try:
                    with open(port_file, encoding='utf-8') as f:
                        port = int(f.readline().strip())
                    break
                except (OSError, ValueError):
                    pass
            if not port:
                return False, '登录窗口没打开'
            async with s.get(f'http://127.0.0.1:{port}/json/version', timeout=aiohttp.ClientTimeout(total=5)) as r:
                ws_url = (await r.json(content_type=None)).get('webSocketDebuggerUrl')
            async with s.ws_connect(ws_url, max_msg_size=0) as ws:
                seq = 0
                loop = asyncio.get_event_loop()
                end = loop.time() + timeout
                last_try = ''
                while loop.time() < end:
                    seq += 1
                    await ws.send_str(json.dumps({'id': seq, 'method': 'Storage.getCookies'}))
                    while True:
                        msg = await ws.receive(timeout=10)
                        if msg.type != aiohttp.WSMsgType.TEXT:  # 窗口关了，浏览器跟着退出
                            return False, '登录窗口被关掉了，还没登录好'
                        m = json.loads(msg.data)
                        if m.get('id') == seq:
                            break
                    ck = cookie_text(src, (m.get('result') or {}).get('cookies') or [])
                    if ck and ck != last_try:
                        last_try = ck
                        ok, why = await check(src, ck)
                        if ok:
                            seq += 1
                            try:  # 登好了：把窗口关掉
                                await ws.send_str(json.dumps({'id': seq, 'method': 'Browser.close'}))
                            except (aiohttp.ClientError, ConnectionResetError):
                                pass
                            return True, why
                        log.info('官网登录读到了登录信息，但核对没过：%s', why)
                    await asyncio.sleep(2)
                try:
                    await ws.send_str(json.dumps({'id': seq + 1, 'method': 'Browser.close'}))
                except (aiohttp.ClientError, ConnectionResetError):
                    pass
                return False, '等了 5 分钟还没登录好，再点一次「登录」'
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        return False, f'登录窗口出错了：{e}'
    finally:
        if proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
