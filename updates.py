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

VERSION = '0.9.15.4'
REPO = 'xShadowMoon/Danmist'  # 2026-11-25 仓库从 bili-danmaku-board 改名成 Danmist（旧地址 GitHub 会自动转过来）
REPOS = ('xshadowmoon/bili-danmaku-board', 'xshadowmoon/danmist')  # 下载地址认这两个名字（比的时候不分大小写）
LATEST_API = f'https://api.github.com/repos/{REPO}/releases/latest'
RELEASES_PAGE = f'https://github.com/{REPO}/releases/latest'
# 国内从 GitHub 下载常常超时（2026-11-26）：直连不行就依次换这些公共加速再试。文件一律按 GitHub 接口给的 sha256 核对，
# 加速站改过的文件装不上。全都不行就提示去百度网盘下安装包
MIRRORS = ('', 'https://ghfast.top/', 'https://gh-proxy.com/')
MIRROR_NAMES = {'': 'GitHub', 'https://ghfast.top/': '国内加速 1', 'https://gh-proxy.com/': '国内加速 2'}
# 查新版本：GitHub 接口连不上时走这个（2026-11-26）。只用来提示「有新版本」——经它拿到的信息不带校验码，
# 下载时还要直接从 GitHub 拿到校验码才下，免得加速站给一个假的新版本
API_MIRROR = 'https://gh-proxy.com/'
PROBE_BYTES = 512 * 1024   # 下载前每个地址先试下这么多，按速度排先后
SLOW_BPS = 100 * 1024      # 下了 15 秒平均还不到这个速度，换下一个地址（最后一个就慢慢下完）
NETDISK = 'https://pan.baidu.com/s/1Ag5Ykctgn8S5OyVNB30jSg?pwd=xn55'
FIRST_DELAY = 20          # 启动后等一会儿再查，先让直播间连上
INTERVAL = 24 * 3600      # 之后每天查一次
RESTART_CODE = 75         # 服务用这个退出码告诉启动器：换上新版本再开

log = logging.getLogger('danmaku')


def parse(tag):
    """'v0.9.2' -> (0, 9, 2, 0)；认不出来就返回 None。
    2026-11-27：只修 bug 的小更新在后面再加一位（0.9.15.1），所以最多认四位，少的补 0 好比大小"""
    m = re.fullmatch(r'v?(\d{1,4})\.(\d{1,4})(?:\.(\d{1,4}))?(?:\.(\d{1,4}))?', str(tag or '').strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def is_newer(tag, current=VERSION):
    latest, now = parse(tag), parse(current)
    return bool(latest and now and latest > now)


async def fetch_latest(session, url=LATEST_API, mirror=True):
    """返回 {'v', 'url' 发布页, 'name' 标题, 'zip'/'sha'/'size' Windows 压缩包}；查不到返回 None。
    GitHub 连不上时再经国内加速问一次（mirror=False 不问），这样拿到的带 'via': 'mirror'，没有校验码"""
    try:
        async with session.get(url, headers={'Accept': 'application/vnd.github+json'},
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
    except Exception as e:  # 断网、超时、GitHub 限流都不算错，明天再查
        if mirror and url == LATEST_API:
            info = await fetch_latest(session, API_MIRROR + url, mirror=False)
            if info:
                log.info('GitHub 连不上（%s），经国内加速查到最新版本 %s', type(e).__name__, info['v'])
                info.pop('digest', None)
                info.pop('sha', None)
                info['via'] = 'mirror'
                return info
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
            dg = str(a.get('digest') or '')
            if re.fullmatch(r'sha256:[0-9a-f]{64}', dg):
                info['digest'] = dg[7:]  # GitHub 自己算的校验码（2026-11-26 起优先用它，加速站下的也按它核对）
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
    if info and info.get('via') == 'mirror':
        raise ValueError(f'连不上 GitHub，没法核对新版本的文件，为了安全这里不下载。可以去百度网盘下载新版安装包，直接装一遍就是升级：{NETDISK}')
    if not info or not info.get('zip') or not (info.get('sha') or info.get('digest')):
        raise ValueError('这个版本没有 Windows 压缩包，去 GitHub 手动下载')
    d = update_dir(app_dir)
    os.makedirs(d, exist_ok=True)
    zpath = os.path.join(d, 'new.zip')
    want = info.get('digest') or ''
    if not want:  # 旧的发布没有 GitHub 校验码：下 .sha256 文件（这个只从 GitHub 直接下，不走加速站）
        async with session.get(info['sha'], timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status != 200:
                raise ValueError(f'校验文件下载失败（{r.status}）')
            want = ((await r.text()).split() or [''])[0].strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', want):
        raise ValueError('校验文件格式不对')
    mirrors = list(MIRRORS if info.get('digest') else ('',))
    if len(mirrors) > 1:  # 先每个地址试下一小段，快的排前面（2026-11-26：国内常常是 GitHub 能连上但很慢）
        speeds = await asyncio.gather(*(_probe(session, m + info['zip']) for m in mirrors))
        mirrors = [m for _, m in sorted(zip(speeds, mirrors), key=lambda x: -x[0])]
        log.info('更新下载地址测速：%s', '，'.join(f'{MIRROR_NAMES.get(m, m)} {s // 1024} KB/s' for s, m in zip(speeds, list(MIRRORS))))
    why = []
    for i, m in enumerate(mirrors):
        name = MIRROR_NAMES.get(m, m)
        try:
            await _fetch(session, m + info['zip'], zpath, want, int(info.get('size') or 0),
                         (lambda p, n=name: progress(p, n)) if progress else None, give_up_slow=i < len(mirrors) - 1)
            if m:
                log.info('用 %s 下好了更新', name)
            break
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
            why.append(f"{m or 'GitHub'}：{e or type(e).__name__}")
            log.info('更新下载失败（%s）：%s', m or 'GitHub', e)
    else:
        raise ValueError('GitHub 和国内加速都没下载成功（' + '；'.join(why)[:200] + f'）。可以去百度网盘下载新版安装包，直接装一遍就是升级：{NETDISK}')
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
        progress(100, "")
    return info['v']


class TooSlow(ValueError):
    pass


async def _probe(session, url):
    """试着下一小段，回每秒多少字节；连不上、出错回 0"""
    loop = asyncio.get_event_loop()
    t0, got = loop.time(), 0
    try:
        async with session.get(url, headers={'Range': f'bytes=0-{PROBE_BYTES - 1}'},
                               timeout=aiohttp.ClientTimeout(total=10, sock_connect=6)) as r:
            if r.status not in (200, 206):
                return 0
            async for chunk in r.content.iter_chunked(64 * 1024):
                got += len(chunk)
                if got >= PROBE_BYTES:
                    break
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        pass
    return int(got / max(loop.time() - t0, 0.05)) if got >= 64 * 1024 else 0


async def _fetch(session, url, zpath, want, size, progress, give_up_slow=False):
    """下载一个压缩包到 zpath，边下边算 sha256，对不上就删掉报错。
    give_up_slow：下了 15 秒还太慢就放弃（后面还有别的地址可以换）"""
    h, got, total = hashlib.sha256(), 0, size
    t0 = asyncio.get_event_loop().time()
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=1800, sock_connect=15, sock_read=60)) as r:
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
                spent = asyncio.get_event_loop().time() - t0
                if give_up_slow and spent > 15 and got / spent < SLOW_BPS and (not total or got < total * 0.8):
                    raise TooSlow(f'太慢了（{int(got / spent / 1024)} KB/s），换一个地址')
    if h.hexdigest() != want:
        os.remove(zpath)
        raise ValueError('下载的文件校验不对（没下完或者被改过）')


def add_site_packages(root, app_dir, say=print):
    """python 文件夹整个换不了（正在用），但新版本可能多了要用的库（比如 0.9.15 的独立窗口要 pywebview）：
    只把自带 Python 里还没有的库文件补进去，已经有的一个都不动（2026-11-27）"""
    src = os.path.join(root, 'python', 'Lib', 'site-packages')
    dst = os.path.join(app_dir, 'python', 'Lib', 'site-packages')
    if not (os.path.isdir(src) and os.path.isdir(dst)):
        return 0
    n = 0
    for base, _, files in os.walk(src):
        out = os.path.join(dst, os.path.relpath(base, src))
        for f in files:
            to = os.path.join(out, f)
            if os.path.exists(to):
                continue
            try:
                os.makedirs(out, exist_ok=True)
                shutil.copy2(os.path.join(base, f), to)
                n += 1
            except OSError as e:
                say(f'新库没装上：{f}（{e}）')
    if n:
        say(f'补上了 {n} 个新库文件')
    return n


def apply(app_dir, say=print, later=()):
    """启动器在服务停下以后调用：把 data/update 里准备好的新版本拷过来（不动 KEEP 里的），成功返回版本号"""
    v, root = staged(app_dir)
    if not v:
        return None
    add_site_packages(root, app_dir, say)
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
