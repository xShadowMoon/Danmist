"""版本号、「有新版本」检查，和桌面版的软件内更新。

只读 GitHub 上最新 Release 的版本号，有更新就在管理页面上提示一下。config.json 里 "update_check": false 可以关掉。
2026-11-25 起（桌面版）：管理身份在页面上点「下载更新」才会下载 Release 里的 Windows 压缩包，
对过 .sha256 后解压到 data/update/，点「重启生效」时由启动器（desktop.py / start.bat）换上新文件再重开。
config.json、data、python 这几个不会被覆盖。
Version number, the "new version available" check, and in-app updates for the desktop launcher:
downloads only when an admin clicks "download update", verifies the .sha256, stages it under
data/update/ and lets the launcher swap the files on restart.
"""
import asyncio
import hashlib
import logging
import os
import re
import shutil
import zipfile

import aiohttp

VERSION = '0.9.6'
REPO = 'xShadowMoon/Danmist'  # 2026-11-25 仓库从 bili-danmaku-board 改名成 Danmist（旧地址 GitHub 会自动转过来）
REPOS = ('xshadowmoon/bili-danmaku-board', 'xshadowmoon/danmist')  # 下载地址认这两个名字（比的时候不分大小写）
LATEST_API = f'https://api.github.com/repos/{REPO}/releases/latest'
RELEASES_PAGE = f'https://github.com/{REPO}/releases/latest'
FIRST_DELAY = 20          # 启动后等一会儿再查，先让直播间连上
INTERVAL = 24 * 3600      # 之后每天查一次
RESTART_CODE = 75         # 服务用这个退出码告诉启动器：换上新版本再开

log = logging.getLogger('danmaku')


def parse(tag):
    """'v0.9.2' -> (0, 9, 2)；认不出来就返回 None。"""
    m = re.fullmatch(r'v?(\d{1,4})\.(\d{1,4})(?:\.(\d{1,4}))?', str(tag or '').strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def is_newer(tag, current=VERSION):
    latest, now = parse(tag), parse(current)
    return bool(latest and now and latest > now)


async def fetch_latest(session, url=LATEST_API):
    """返回 {'v', 'url' 发布页, 'name' 标题, 'zip'/'sha'/'size' Windows 压缩包}；查不到返回 None。"""
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
    if not any(page.lower().startswith(f'https://github.com/{r}/') for r in REPOS):
        page = RELEASES_PAGE
    info = {'v': tag.lstrip('v'), 'url': page, 'name': str(data.get('name') or '')[:120]}
    # 桌面版自己更新用：Windows 压缩包和它的 .sha256（只认这个仓库的下载地址）
    for a in data.get('assets') or []:
        u = str((a or {}).get('browser_download_url') or '')
        if not any(u.lower().startswith(f'https://github.com/{r}/releases/download/') for r in REPOS):
            continue
        if u.endswith('-windows-x64.zip'):
            info['zip'], info['size'] = u, int(a.get('size') or 0)
        elif u.endswith('-windows-x64.zip.sha256'):
            info['sha'] = u
    return info


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


# ---------- 桌面版：下载、校验、解压、换文件（2026-11-25） ----------
KEEP = {'config.json', 'data', 'python', 'admin.key'}  # 这些不动：设置、存档、自带的 Python（正在用，换不了）


def update_dir(app_dir):
    return os.path.join(app_dir, 'data', 'update')


def staged(app_dir):
    """已经下载好、等重启换上的版本：返回 (版本号, 文件夹)；没有就 (None, None)"""
    try:
        with open(os.path.join(update_dir(app_dir), 'ready.txt'), encoding='utf-8') as f:
            v, folder = f.read().splitlines()[:2]
        if parse(v) and os.path.isfile(os.path.join(folder, 'server.py')):
            return v, folder
    except (OSError, ValueError):
        pass
    return None, None


async def download(session, info, app_dir, progress=None):
    """下载新版压缩包，对 sha256，解压到 data/update/v版本/。成功返回版本号，失败抛 ValueError（中文原因）"""
    if not info or not info.get('zip') or not info.get('sha'):
        raise ValueError('这个版本没有 Windows 压缩包，去 GitHub 手动下载')
    d = update_dir(app_dir)
    os.makedirs(d, exist_ok=True)
    zpath = os.path.join(d, 'new.zip')
    async with session.get(info['sha'], timeout=aiohttp.ClientTimeout(total=30)) as r:
        if r.status != 200:
            raise ValueError(f'校验文件下载失败（{r.status}）')
        want = ((await r.text()).split() or [''])[0].strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', want):
        raise ValueError('校验文件格式不对')
    h, got, total = hashlib.sha256(), 0, int(info.get('size') or 0)
    async with session.get(info['zip'], timeout=aiohttp.ClientTimeout(total=1800, sock_read=60)) as r:
        if r.status != 200:
            raise ValueError(f'压缩包下载失败（{r.status}）')
        total = int(r.headers.get('Content-Length') or total or 0)
        with open(zpath, 'wb') as f:
            async for chunk in r.content.iter_chunked(256 * 1024):
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if got > 300 * 1024 * 1024:
                    raise ValueError('压缩包太大了，不对劲')
                if progress and total:
                    progress(min(99, got * 100 // total))
    if h.hexdigest() != want:
        os.remove(zpath)
        raise ValueError('下载的文件校验不对（可能没下完），再点一次')
    folder = os.path.join(d, 'v' + info['v'])
    shutil.rmtree(folder, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            parts = m.filename.replace('\\', '/').split('/')
            if m.filename.startswith(('/', '\\')) or '..' in parts or ':' in parts[0]:
                raise ValueError('压缩包里有不安全的路径')
        z.extractall(folder)
    os.remove(zpath)
    inner = [os.path.join(folder, x) for x in os.listdir(folder)]
    root = inner[0] if len(inner) == 1 and os.path.isdir(inner[0]) else folder  # 压缩包里套了一层文件夹
    if not os.path.isfile(os.path.join(root, 'server.py')):
        raise ValueError('压缩包里没有 server.py，不像是雾幕')
    with open(os.path.join(d, 'ready.txt'), 'w', encoding='utf-8') as f:
        f.write(info['v'] + '\n' + root + '\n')
    if progress:
        progress(100)
    return info['v']


def apply(app_dir, say=print, later=()):
    """启动器在服务停下以后调用：把 data/update 里准备好的新版本拷过来（不动 KEEP 里的），成功返回版本号"""
    v, root = staged(app_dir)
    if not v:
        return None
    for name in os.listdir(root):
        if name in KEEP:
            continue
        src, dst = os.path.join(root, name), os.path.join(app_dir, name)
        if name in later:  # start.bat 正在跑，不能当场改它：先放成 .new，下次桌面版启动时换
            dst += '.new'
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        except OSError as e:
            say(f'更新时有文件没换上：{name}（{e}）')
    shutil.rmtree(update_dir(app_dir), ignore_errors=True)
    say(f'已经换成 v{v}')
    return v


if __name__ == '__main__':
    import sys
    if sys.argv[1:2] == ['--apply']:
        apply(os.path.dirname(os.path.abspath(__file__)), later=('start.bat',) if '--from-bat' in sys.argv else ())
