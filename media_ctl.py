"""控制音乐客户端的播放 / 暂停（2026-11-28 用户：有人点歌要自己开始放；点的歌放完别接着放主播以前的队列）。

用 Windows 自带的媒体控制（media_ctl.ps1），只动网易云 / QQ 音乐自己，不碰游戏和别的程序。
做不了（不是 Windows、客户端没接 Windows 媒体控制）就当没这回事，点歌照常。
"""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = {'163': 'cloudmusic', 'qq': 'QQMusic'}  # Windows 媒体控制里这两个客户端的名字


async def run(src, do):
    """do = play / pause / status。返回客户端现在的状态（Playing / Paused / none …），做不了返回空"""
    app = APPS.get(src)
    if sys.platform != 'win32' or not app:
        return ''
    try:
        proc = await asyncio.create_subprocess_exec(
            'powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', os.path.join(HERE, 'media_ctl.ps1'),
            '-App', app, '-Do', do, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            creationflags=0x08000000)  # 不出黑窗口
        out, _ = await asyncio.wait_for(proc.communicate(), 20)
        return out.decode('utf-8', 'replace').strip()
    except (OSError, asyncio.TimeoutError):
        return ''
