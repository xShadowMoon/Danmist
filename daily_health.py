"""每日只读体检；耗时磁盘检查在线程内运行，不读取账号凭据。"""
import asyncio
import datetime as dt
import json
import logging
import shutil
import time
import zipfile
import zlib
from pathlib import Path

import aiohttp
import retention

log = logging.getLogger('xiaowu')
GB = 1024 ** 3


def tree_size(root, folder):
    if not folder.exists():
        return 0
    if not retention.safe_inside(root, folder, directory=True):
        raise OSError('目录不是服务范围内的普通目录')
    pending, total = [folder], 0
    while pending:
        current = pending.pop()
        if not retention.safe_inside(root, current, directory=True):
            continue
        for path in current.iterdir():
            if retention.safe_inside(root, path, directory=True):
                pending.append(path)
            elif retention.safe_inside(root, path):
                total += path.stat().st_size
    return total


def disk_checks(root, now):
    root = Path(root)
    data, backup = root / 'data', root / '备份'
    rows = []
    def add(key, ok, detail, **extra):
        rows.append({'id': key, 'ok': ok, 'detail': detail, **extra})
    try:
        usage = shutil.disk_usage(data)
        ratio = usage.free / usage.total if usage.total else 0
        add('disk', usage.free >= 5 * GB and ratio >= .05,
            f'磁盘剩余 {usage.free / GB:.1f} GB（{ratio:.1%}）' + ('，请腾出磁盘空间' if usage.free < 5 * GB or ratio < .05 else ''),
            free_bytes=usage.free, total_bytes=usage.total)
    except OSError:
        add('disk', False, '读不到磁盘空间，请检查数据盘是否连接')
    for key, folder in (('data_size', data), ('backup_size', backup)):
        try:
            size = tree_size(root, folder)
            add(key, True, f'{"数据" if key == "data_size" else "备份"}占用 {size / GB:.2f} GB', bytes=size)
        except OSError:
            add(key, False, '无法统计目录大小，请检查目录权限')
    today = dt.datetime.fromtimestamp(now).date()
    valid_backup = False
    for day in (today, today - dt.timedelta(days=1)):
        path = backup / '数据' / f'data-{day:%Y%m%d}.zip'
        if not retention.safe_inside(root, path):
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.infolist() and archive.testzip() is None:
                    valid_backup = True
                    break
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, EOFError, zlib.error, NotImplementedError):
            pass
    add('backup', valid_backup, '昨天或今天的备份可读取' if valid_backup else '昨天和今天没有可用备份，请检查备份任务和磁盘空间')
    try:
        expiring = 0
        folder = data / 'accounts'
        if retention.safe_inside(root, folder, directory=True):
            for path in retention.iter_plain_files(folder, retention.ACCOUNT_FILE):
                remaining = retention.ACCOUNT_IDLE_DAYS * retention.DAY - (now - path.stat().st_mtime)
                if remaining < 14 * retention.DAY:
                    expiring += 1
        add('accounts', not expiring, f'{expiring} 个网页登录账号快到本地保留期限，请在网页使用或重新扫码登录' if expiring else '网页登录账号未接近本地保留期限', count=expiring)
    except OSError:
        add('accounts', False, '无法检查网页登录记录，请检查账号目录权限')
    return rows


async def tunnel_check(session, public_url):
    try:
        async with session.get(public_url.rstrip('/') + '/api/ping', timeout=aiohttp.ClientTimeout(total=20)) as response:
            return response.status == 200 and await response.text() == 'ok'
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return False


class DailyHealth:
    def __init__(self, root, writer, persist=True, hour=9):
        self.root, self.writer, self.hour = Path(root), writer, hour
        self.path = str(self.root / 'data' / 'daily-health.json') if persist else None
        self.state = {'day': '', 'checked_day': '', 'checked_at': 0, 'checks': []}
        self.dirty = False
        if self.path:
            try:
                with open(self.path, encoding='utf-8') as f:
                    saved = json.load(f)
                if (isinstance(saved, dict) and isinstance(saved.get('checks'), list) and len(saved['checks']) <= 16
                        and type(saved.get('checked_at')) in (int, float) and 0 <= saved['checked_at'] <= 4102444800
                        and all(isinstance(saved.get(k), str) and len(saved[k]) <= 10 for k in ('day', 'checked_day'))
                        and all(isinstance(r, dict) and type(r.get('ok')) is bool and isinstance(r.get('detail'), str)
                                and len(r['detail']) <= 500 for r in saved['checks'])):
                    self.state = saved
            except (OSError, ValueError, TypeError):
                pass

    async def save(self):
        if self.path and self.dirty:
            try:
                await asyncio.to_thread(self.writer, self.path, self.state)
                self.dirty = False
            except OSError:
                log.warning('每日体检结果保存失败，将稍后重试')

    def snapshot(self):
        return {'checked_at': self.state['checked_at'], 'checks': self.state['checks']}

    async def run(self, room, session, public_url, sender, enabled=True, now=None):
        now = time.time() if now is None else now
        current = dt.datetime.fromtimestamp(now)
        day = current.strftime('%Y-%m-%d')
        await self.save()
        if current.hour < self.hour or self.state['day'] >= day:
            return False
        if self.state['checked_day'] != day:
            rows = await asyncio.to_thread(disk_checks, self.root, now)
            tunnel = await tunnel_check(session, public_url)
            rows += [
                {'id': 'tunnel', 'ok': tunnel, 'detail': '外网访问正常' if tunnel else '外网打不开，请检查隧道和网络'},
                {'id': 'bili', 'ok': room.get('bili_ok') is True, 'detail': 'B 站连接正常' if room.get('bili_ok') is True else 'B 站连接未就绪，请检查网络和直播间连接'},
                {'id': 'login', 'ok': room.get('login_ok') is True, 'detail': '机器人登录正常' if room.get('login_ok') is True else '机器人登录未就绪，请到机器人重新扫码登录'},
            ]
            self.state.update(checked_day=day, checked_at=int(now), checks=rows)
            self.dirty = True
            await self.save()
        bad = [r['detail'] for r in self.state['checks'] if not r['ok']]
        if bad and enabled:
            text = ('雾幕每日体检：' + day + '\n' + '\n'.join('• ' + r for r in bad)).encode('utf-16-le')[:3800].decode('utf-16-le', errors='ignore')
            try:
                if not await sender(text):
                    return False
            except Exception:
                return False
        self.state['day'] = day
        self.dirty = True
        await self.save()
        return bool(bad and enabled)
