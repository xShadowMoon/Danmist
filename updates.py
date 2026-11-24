"""版本号和「有新版本」检查。

只读 GitHub 上最新 Release 的版本号，有更新就在管理页面上提示一下，
不会自己下载或改动任何文件。config.json 里 "update_check": false 可以关掉。
Version number and the "new version available" check. Only reads the latest
release's tag from GitHub; never downloads or changes anything.
"""
import asyncio
import logging
import re

import aiohttp

VERSION = '0.9.2'
REPO = 'xShadowMoon/bili-danmaku-board'
LATEST_API = f'https://api.github.com/repos/{REPO}/releases/latest'
RELEASES_PAGE = f'https://github.com/{REPO}/releases/latest'
FIRST_DELAY = 20          # 启动后等一会儿再查，先让直播间连上
INTERVAL = 24 * 3600      # 之后每天查一次

log = logging.getLogger('danmaku')


def parse(tag):
    """'v0.9.2' -> (0, 9, 2)；认不出来就返回 None。"""
    m = re.fullmatch(r'v?(\d{1,4})\.(\d{1,4})(?:\.(\d{1,4}))?', str(tag or '').strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def is_newer(tag, current=VERSION):
    latest, now = parse(tag), parse(current)
    return bool(latest and now and latest > now)


async def fetch_latest(session, url=LATEST_API):
    """返回 {'v': '0.9.2', 'url': 发布页, 'name': 标题}；查不到返回 None。"""
    try:
        async with session.get(url, headers={'Accept': 'application/vnd.github+json'},
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
    except Exception as e:  # 断网、超时、GitHub 限流都不算错，明天再查
        log.info('检查新版本没成功（%s），明天再试', type(e).__name__)
        return None
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        return None
    tag = str(data.get('tag_name') or '')
    if not parse(tag):
        return None
    page = str(data.get('html_url') or '')
    if not page.startswith(f'https://github.com/{REPO}/'):
        page = RELEASES_PAGE
    return {'v': tag.lstrip('v'), 'url': page, 'name': str(data.get('name') or '')[:120]}


async def watch(session, on_new, url=LATEST_API, first_delay=FIRST_DELAY, interval=INTERVAL):
    """启动后查一次，之后每天一次；发现比现在新的版本就调用 on_new(info)。"""
    await asyncio.sleep(first_delay)
    told = None
    while True:
        info = await fetch_latest(session, url)
        if info and is_newer(info['v']) and info['v'] != told:
            told = info['v']
            log.info('GitHub 上有新版本 %s（现在是 %s）：%s', info['v'], VERSION, info['url'])
            on_new(info)
        await asyncio.sleep(interval)
