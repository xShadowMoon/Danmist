"""历史原地无损压缩与索引核对；不迁走场次，不删除缺失文件对应的索引。"""
import asyncio
import datetime as dt
import gzip
import json
import logging
import os
from pathlib import Path
import re
import shutil
import threading
import time

import retention
import input_validation as validation

log = logging.getLogger('xiaowu')
HISTORY_LOCK = threading.RLock()
DM_NAME = re.compile(rf'({retention.SID})\.dm\.jsonl')
SUMMARY_NAME = re.compile(rf'({retention.SID})\.json')
PART_NAME = re.compile(rf'(?:{retention.SID}\.(?:json|dm\.jsonl(?:\.gz)?)|index\.json)(?:\.tmp|\.part)')


def equal_bytes(source, zipped):
    with source.open('rb') as original, gzip.open(zipped, 'rb') as restored:
        while True:
            left, right = original.read(1024 * 1024), restored.read(1024 * 1024)
            if left != right:
                return False
            if not left:
                return True


def compress_one(root, source, can_run):
    if not retention.safe_inside(root, source) or not can_run():
        return 0, 0
    signature = retention.file_signature(source)
    target, temporary = Path(str(source) + '.gz'), Path(str(source) + '.gz.tmp')
    if target.exists() and not retention.safe_inside(root, target):
        raise OSError('压缩目标不是普通文件')
    if not target.exists():
        # 用独占创建，不能跟随残留链接，也不覆盖上次留下的待检查文件。
        with temporary.open('xb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as output, source.open('rb') as original:
                shutil.copyfileobj(original, output, 1024 * 1024)
            raw.flush()
            os.fsync(raw.fileno())
        if not equal_bytes(source, temporary):
            raise OSError('压缩前后内容不一致，保留原文件')
        with HISTORY_LOCK:
            if not can_run() or retention.file_signature(source) != signature:
                return 0, 0
            os.replace(temporary, target)
    if not equal_bytes(source, target):
        raise OSError('压缩文件校验失败，保留原文件')
    with HISTORY_LOCK:
        if not can_run() or retention.file_signature(source) != signature or not retention.safe_inside(root, source):
            return 0, 0
        saved = signature[0] - target.stat().st_size
        log.info('历史弹幕压缩已逐字节核对：%s', source.name)
        source.unlink()
    return 1, saved


def repair_index(root, folder, writer, can_run):
    index = folder / 'index.json'
    if index.exists() and not retention.safe_inside(root, index):
        return 0
    with HISTORY_LOCK:
        if not can_run():
            return 0
        try:
            with index.open(encoding='utf-8') as f:
                rows = json.load(f)
            if not isinstance(rows, list):
                raise ValueError()
        except FileNotFoundError:
            rows = []
        except (OSError, ValueError):
            log.warning('历史索引无法读取，保留原文件等待修复')
            return 0
        ids = {r.get('id') for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str)}
        for sid in ids:
            if re.fullmatch(retention.SID, sid) and not (folder / (sid + '.json')).is_file():
                log.warning('历史场次文件缺失，保留索引项：%s', sid)
        added = 0
        for path in folder.iterdir():
            match = SUMMARY_NAME.fullmatch(path.name)
            if not match or match[1] in ids or not retention.safe_inside(root, path):
                continue
            try:
                with path.open(encoding='utf-8') as f:
                    summary = validation.history_row(json.load(f))
                # 早期场次可能没有 brief，用原有摘要字段补回，完整场次文件保持不动。
                brief_fields = {'id', 'start', 'end', 'title', 'total', 'income', 'flow', 'dm_total',
                                'user_count', 'sc_count', 'guard_count', 'peak_online', 'reason'}
                brief = validation.history_row(summary.get('brief') or {k: v for k, v in summary.items() if k in brief_fields})
                if summary['id'] != match[1] or brief['id'] != match[1] or 'start' not in brief:
                    raise ValueError()
                rows.append(brief)
                ids.add(match[1])
                added += 1
            except (OSError, ValueError, KeyError, TypeError):
                log.warning('无法从历史场次补回索引：%s', path.name)
        if added and can_run():
            writer(str(index), rows)
            return added
        return 0


def organize(root, writer, can_run, now=None, batch=50, protected=()):
    now = time.time() if now is None else now
    root = Path(root)
    data, history = root / 'data', root / 'data' / 'history'
    marker = data / 'history-maintenance.json'
    month = dt.datetime.fromtimestamp(now).strftime('%Y-%m')
    result = {'ran': False, 'compressed': 0, 'saved_bytes': 0, 'index_added': 0, 'pending': False}
    if not can_run() or not retention.safe_inside(root, history, directory=True):
        return result
    previous = {}
    if marker.exists():
        if not retention.safe_inside(root, marker):
            return result
        try:
            with marker.open(encoding='utf-8') as f:
                previous = json.load(f)
            last = previous.get('last_run', 0) if isinstance(previous, dict) else 0
            if (isinstance(previous, dict) and not previous.get('pending') and type(last) in (int, float)
                    and 0 <= now - last < 30 * retention.DAY):
                return result
        except (OSError, ValueError):
            pass
    result['ran'] = True
    candidates = []
    for folder in sorted(history.iterdir()):
        if not folder.name.isascii() or not folder.name.isdigit() or not retention.safe_inside(root, folder, directory=True):
            continue
        if not can_run():
            result['pending'] = True
            break
        result['index_added'] += repair_index(root, folder, writer, can_run)
        # 先处理过期中间文件，避免同一批次的旧临时文件挡住独占创建。
        for path in sorted(folder.iterdir()):
            if not can_run():
                result['pending'] = True
                break
            if not retention.safe_inside(root, path):
                continue
            if any(folder.name == room and path.name.startswith(sid + '.') for room, sid in protected):
                continue
            age = now - path.stat().st_mtime
            if PART_NAME.fullmatch(path.name) and age > retention.DAY:
                retention.remove_data_file(path, '历史整理：中间文件超过 1 天')
            elif DM_NAME.fullmatch(path.name) and age > 30 * retention.DAY:
                candidates.append(path)
    cursor = previous.get('cursor', '') if isinstance(previous, dict) else ''
    if not isinstance(cursor, str):
        cursor = ''
    key = lambda p: str(p.relative_to(history))
    # 上批失败的文件也有游标，不能让最前面的坏文件永远挡住后面的好文件。
    candidates = [p for p in candidates if key(p) > cursor] + [p for p in candidates if key(p) <= cursor]
    if len(candidates) > batch:
        result['pending'] = True
    for path in candidates[:batch]:
        if not can_run():
            result['pending'] = True
            break
        cursor = key(path)
        try:
            count, saved = compress_one(root, path, can_run)
            result['compressed'] += count
            result['saved_bytes'] += saved
            if not count:
                result['pending'] = True
        except (OSError, EOFError, ValueError):
            result['pending'] = True
            log.warning('历史弹幕压缩未完成，保留原文件：%s', path.name)
    writer(str(marker), {'month': month, 'last_run': int(now), 'cursor': cursor, **result})
    log.info('历史整理完成：压缩 %d 个文件，节省 %d 字节，补回 %d 条索引',
             result['compressed'], result['saved_bytes'], result['index_added'])
    return result


async def maintain(hub, root, writer):
    if hub.state.room.get('live') == 1:
        return {'ran': False}
    archive = hub.state.archive_id
    can_run = lambda: hub.state.room.get('live') != 1 and hub.state.archive_id == archive
    protected = {(str(hub.state.room_id), archive)}
    if hub.state.archive_pending:
        protected.add((str(hub.state.room_id), hub.state.archive_pending['id']))
    result = await asyncio.to_thread(organize, root, writer, can_run, protected=protected)
    if result['ran']:
        hub.history._viewers, hub.history._dm = None, (None, None)
    return result
