"""训练自己的音色（2026-11-28 用户定的方案：安装包不带，软件里点了再下载）。

用的是 GPT-SoVITS 官方的 Windows 整合包（Hugging Face 上 lj1995/GPT-SoVITS-windows-package，v2Pro 版）：
- 要 N 卡（显存 6GB 以上，8GB 更稳），下载约 8.2GB，解压后约 12GB
- 训练在 GPT-SoVITS 自己的网页里做（切录音、认字、训练），雾幕负责下载、打开它、训练好以后把音色接进朗读
- 已经自己装了 GPT-SoVITS 的，直接选那个文件夹就行，不用再下
下载前先测哪个源快（Hugging Face / 国内镜像），断了能接着下；解压用 7-Zip 官网的 7zr.exe（很小，用到时才下）。
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys
import time
import wave

import aiohttp

REPO = 'lj1995/GPT-SoVITS-windows-package'
PACKAGES = {  # 键：(文件名, 大约多大)
    'normal': ('GPT-SoVITS-v2pro-20250604.7z', 8_190_000_000),
    'rtx50': ('GPT-SoVITS-v2pro-20250604-nvidia50.7z', 8_840_000_000),  # RTX 50 系显卡要这个
}
SOURCES = [('Hugging Face', f'https://huggingface.co/{REPO}/resolve/main/'),
           ('国内镜像', f'https://hf-mirror.com/{REPO}/resolve/main/')]
SEVENZR = 'https://www.7-zip.org/a/7zr.exe'
NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0
NEED_VRAM_MB = 6000
NEED_FREE_GB = 15


def gpus():
    """N 卡的名字和显存（MB）。没有 N 卡 / 没装驱动返回 []"""
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                           capture_output=True, timeout=10, creationflags=NO_WINDOW)
        out = []
        for line in r.stdout.decode('utf-8', 'replace').splitlines():
            if ',' in line:
                name, mem = line.rsplit(',', 1)
                try:
                    out.append({'name': name.strip(), 'mb': int(float(mem.strip()))})
                except ValueError:
                    pass
        return out
    except (OSError, subprocess.SubprocessError):
        return []


def free_gb(path):
    p = os.path.abspath(path or '.')
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        return round(shutil.disk_usage(p).free / 1024 ** 3, 1)
    except OSError:
        return 0.0


def find_root(folder):
    """GPT-SoVITS 的根目录（里面有 api_v2.py 和 webui.py）。整合包解压出来多一层文件夹，往下找两层"""
    if not folder or not os.path.isdir(folder):
        return ''
    queue = [(os.path.abspath(folder), 0)]
    while queue:
        d, depth = queue.pop(0)
        if os.path.isfile(os.path.join(d, 'api_v2.py')) and os.path.isfile(os.path.join(d, 'webui.py')):
            return d
        if depth < 2:
            try:
                queue += [(os.path.join(d, n), depth + 1) for n in sorted(os.listdir(d))
                          if os.path.isdir(os.path.join(d, n)) and not n.startswith(('.', '_'))]
            except OSError:
                pass
    return ''


def python_of(root):
    """整合包自带的 Python（runtime\\python.exe）；自己装的没有就用系统的 python"""
    p = os.path.join(root, 'runtime', 'python.exe')
    return p if os.path.isfile(p) else 'python'


def check(folder):
    g = gpus()
    best = max((x['mb'] for x in g), default=0)
    root = find_root(folder)
    return {'gpus': g, 'gpu_ok': best >= NEED_VRAM_MB, 'rtx50': any(re.search(r'RTX\s*50\d0', x['name'], re.I) for x in g),
            'free_gb': free_gb(folder), 'need_gb': NEED_FREE_GB, 'need_vram_gb': NEED_VRAM_MB // 1000, 'root': root,
            'has_webui': bool(root and os.path.isfile(os.path.join(root, 'go-webui.bat'))),
            'packages': {k: {'file': v[0], 'gb': round(v[1] / 1e9, 1)} for k, v in PACKAGES.items()}}


def wav_seconds(path):
    try:
        with wave.open(path, 'rb') as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except (OSError, wave.Error, EOFError):
        return 0.0


def scan(root):
    """训练出来的模型（GPT_weights*/*.ckpt、SoVITS_weights*/*.pth，新的在前）和能当参考音频的片段（3~10 秒，带识别出的文字）"""
    out = {'gpt': [], 'sovits': [], 'refs': []}
    if not root or not os.path.isdir(root):
        return out
    for d in os.listdir(root):
        full = os.path.join(root, d)
        if not os.path.isdir(full):
            continue
        kind = 'gpt' if d.startswith('GPT_weights') else 'sovits' if d.startswith('SoVITS_weights') else ''
        if not kind:
            continue
        ext = '.ckpt' if kind == 'gpt' else '.pth'
        for n in os.listdir(full):
            if n.endswith(ext):
                p = os.path.join(full, n)
                out[kind].append({'path': p, 'name': f'{d}/{n}', 't': int(os.path.getmtime(p))})
    for k in ('gpt', 'sovits'):
        out[k].sort(key=lambda x: -x['t'])
    asr = os.path.join(root, 'output', 'asr_opt')
    if os.path.isdir(asr):
        for n in sorted(os.listdir(asr)):
            if not n.endswith('.list'):
                continue
            try:
                with open(os.path.join(asr, n), encoding='utf-8') as f:
                    for line in f:
                        parts = line.rstrip('\n').split('|')
                        if len(parts) < 4:
                            continue
                        wav, lang, text = parts[0], parts[2].lower(), parts[3].strip()
                        if not os.path.isabs(wav):
                            wav = os.path.join(root, wav)
                        sec = wav_seconds(wav)
                        if 3 <= sec <= 10 and text:
                            out['refs'].append({'path': wav, 'text': text[:200], 'lang': lang if lang in ('zh', 'ja', 'en', 'ko', 'yue') else 'zh',
                                                'sec': round(sec, 1)})
            except OSError:
                pass
    out['refs'] = sorted(out['refs'], key=lambda r: abs(r['sec'] - 6))[:30]  # 6 秒左右的最合适
    return out


def open_webui(root):
    """打开 GPT-SoVITS 自己的训练网页（会弹一个黑窗口，网页自己在浏览器里打开）"""
    bat = os.path.join(root, 'go-webui.bat')
    if not os.path.isfile(bat):
        raise ValueError('这个文件夹里没有 go-webui.bat，不像 GPT-SoVITS 整合包')
    subprocess.Popen(['cmd', '/c', 'start', 'GPT-SoVITS', 'go-webui.bat'], cwd=root, creationflags=NO_WINDOW)


def start_api(root, port=9880):
    """在后台开 GPT-SoVITS 的合成接口（api_v2.py），雾幕朗读要它。返回进程"""
    if not os.path.isfile(os.path.join(root, 'api_v2.py')):
        raise ValueError('这个文件夹里没有 api_v2.py')
    log = open(os.path.join(root, 'danmist-api.log'), 'ab')
    return subprocess.Popen([python_of(root), 'api_v2.py', '-a', '127.0.0.1', '-p', str(port)], cwd=root,
                            stdout=log, stderr=log, creationflags=NO_WINDOW)


class Installer:
    """下载 + 解压，一次只跑一个。progress(dict) 报进度"""

    def __init__(self):
        self.task = None
        self.state = {'stage': '', 'pct': 0, 'msg': ''}

    def busy(self):
        return self.task is not None and not self.task.done()

    def cancel(self):
        if self.busy():
            self.task.cancel()

    async def probe(self, session, name):
        """各试下 2MB，按速度排"""
        rows = []
        for label, base in SOURCES:
            t = time.time()
            try:
                async with session.get(base + name, headers={'Range': 'bytes=0-2097151'},
                                       timeout=aiohttp.ClientTimeout(total=20, sock_connect=8)) as r:
                    if r.status not in (200, 206):
                        continue
                    got = 0
                    async for chunk in r.content.iter_chunked(65536):
                        got += len(chunk)
                        if got >= 2097152:
                            break
                rows.append((got / max(0.05, time.time() - t), label, base))
            except (aiohttp.ClientError, asyncio.TimeoutError):
                continue
        return [(label, base) for _, label, base in sorted(rows, reverse=True)]

    async def fetch(self, session, url, dest, size, progress, label):
        part = dest + '.part'
        have = os.path.getsize(part) if os.path.exists(part) else 0
        headers = {'Range': f'bytes={have}-'} if have else {}
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=60)) as r:
            if have and r.status == 200:
                have = 0  # 不支持接着下：从头来
            elif r.status not in (200, 206):
                raise ValueError(f'下载地址回了 {r.status}')
            total = have + int(r.headers.get('Content-Length') or 0) or size
            t0, last, done = time.time(), 0.0, have
            with open(part, 'ab' if have else 'wb') as f:
                async for chunk in r.content.iter_chunked(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if time.time() - last > 1:
                        last = time.time()
                        speed = (done - have) / max(0.5, last - t0)
                        progress({'stage': 'download', 'pct': round(done / total * 100, 1), 'done': done, 'total': total,
                                  'speed': speed, 'src': label, 'left': int((total - done) / speed) if speed > 0 else 0})
        if size and os.path.getsize(part) < size * 0.98:
            raise ValueError('下载的文件不完整，再点一次会接着下')
        os.replace(part, dest)

    async def run(self, session, folder, kind, progress):
        name, size = PACKAGES[kind]
        os.makedirs(folder, exist_ok=True)
        if free_gb(folder) < NEED_FREE_GB and not os.path.exists(os.path.join(folder, name)):
            raise ValueError(f'这个盘剩下的空间不到 {NEED_FREE_GB} GB，换个盘')
        tools = os.path.join(folder, '_tools')
        os.makedirs(tools, exist_ok=True)
        sz = os.path.join(tools, '7zr.exe')
        if not os.path.isfile(sz):
            progress({'stage': 'tools', 'pct': 0, 'msg': '先下解压工具（7-Zip，很小）'})
            async with session.get(SEVENZR, timeout=aiohttp.ClientTimeout(total=120)) as r:
                if r.status != 200:
                    raise ValueError('解压工具下不下来，看看网络')
                data = await r.read()
            with open(sz, 'wb') as f:
                f.write(data)
        archive = os.path.join(folder, name)
        if not os.path.isfile(archive):
            progress({'stage': 'probe', 'pct': 0, 'msg': '在测哪个下载源快'})
            srcs = await self.probe(session, name)
            if not srcs:
                raise ValueError('Hugging Face 和国内镜像都连不上，看看网络')
            last_err = None
            for label, base in srcs:
                try:
                    await self.fetch(session, base + name, archive, size, progress, label)
                    break
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                    last_err = e
            else:
                raise ValueError(f'没下载完：{last_err}（再点一次会接着下）')
        progress({'stage': 'extract', 'pct': 0, 'msg': '正在解压'})
        proc = await asyncio.create_subprocess_exec(sz, 'x', archive, f'-o{folder}', '-y', '-bsp1', '-bso0',
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                    creationflags=NO_WINDOW)
        buf = b''
        try:
            while True:
                chunk = await proc.stdout.read(256)
                if not chunk:
                    break
                buf = (buf + chunk)[-512:]
                m = re.findall(rb'(\d{1,3})%', buf)
                if m:
                    progress({'stage': 'extract', 'pct': int(m[-1]), 'msg': '正在解压'})
            code = await proc.wait()
        except asyncio.CancelledError:
            proc.kill()
            raise
        if code != 0:
            raise ValueError(f'解压没成功（{code}），硬盘空间够不够？')
        root = find_root(folder)
        if not root:
            raise ValueError('解压完了但没找到 GPT-SoVITS 的文件')
        try:
            os.remove(archive)  # 解压好了，压缩包删掉省 8GB
        except OSError:
            pass
        progress({'stage': 'done', 'pct': 100, 'msg': '装好了', 'root': root})
        return root
