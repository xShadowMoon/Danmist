"""保留期限、场次大小和可验证的历史迁移。所有路径都由服务自己的数据目录提供。"""
import itertools
import json
import logging
import os
import re
import stat
import time
import uuid
import zipfile
from pathlib import Path


log = logging.getLogger('xiaowu')
DAY = 86400
OFFLINE_DAYS = 60
GUARD_EXPIRED_DAYS = 365
ACCOUNT_IDLE_DAYS = 180
ACCOUNT_MAX = 64
NOTES_MAX = 10000
EMOTS_MAX = 4096
# 历史场次不自动移走（2026-11-13 Claude 审查时改）：每场只有几百 KB，用户要能在「历史」里一直翻到；
# 冷存档的代码留着，真要用时把这两个数改小即可
HISTORY_DAYS = 36500
HISTORY_MAX = 1000000
HISTORY_EXPORT_BATCH = 128

# 只给原先无界的活跃数据设高水位；达到时结算整个分段，保留所有记录。
SEGMENT_DM_ROWS = 200000
SEGMENT_DM_BYTES = 64 * 1024 * 1024
SEGMENT_USERS = 20000
SEGMENT_SC = 5000
SEGMENT_GUARDS = 5000
SEGMENT_GIFT_TYPES = 5000
SEGMENT_FANS = 10000
SID = r'\d{8}-\d{4}(?:-[0-9a-f]{12})?'
OFFLINE_FILE = re.compile(rf'(?:{SID}|\d{{8}}-\d{{6}})\.json')
ACCOUNT_FILE = re.compile(r'[0-9a-f]{24}\.json')


def is_plain(path, *, directory=False):
    """拒绝链接和 Windows 重解析点，清理不会跨出数据目录。"""
    try:
        info = path.lstat()
    except OSError:
        return False
    mode = stat.S_ISDIR if directory else stat.S_ISREG
    return mode(info.st_mode) and not (
        getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def iter_plain_files(folder, pattern):
    if not is_plain(folder, directory=True):
        return
    for path in folder.iterdir():
        if pattern.fullmatch(path.name) and is_plain(path):
            yield path


def remove_data_file(path, reason):
    if not is_plain(path):
        return False
    log.info('清理数据文件 %s：%s', path.name, reason)
    try:
        path.unlink()
    except OSError as e:
        log.warning('清理失败 %s：%s', path.name, e)
        return False
    return True


def prune_accounts(folder, now=None):
    """过期依据是最近一次用登录凭据的时间，未过期的账号不自动挤掉。"""
    cutoff = (time.time() if now is None else now) - ACCOUNT_IDLE_DAYS * DAY
    for path in iter_plain_files(Path(folder), ACCOUNT_FILE):
        try:
            if path.stat().st_mtime < cutoff:
                remove_data_file(path, '超过 180 天未使用')
        except OSError:
            pass


def trim_emots(emots):
    """旧客户端仍收到原来的 {表情: 地址} 格式。"""
    kept = {}
    for key, value in emots.items():
        if isinstance(key, str) and 0 < len(key) <= 64 and isinstance(value, str) and 0 < len(value) <= 2048:
            kept[key] = value
    if len(kept) > EMOTS_MAX:
        kept = dict(list(kept.items())[-EMOTS_MAX:])
    if len(kept) != len(emots):
        log.info('小表情缓存清理 %d 项', len(emots) - len(kept))
    return kept


def prune_offline(data, room, protected, now=None):
    folder = data / 'offline' / room
    if not is_plain(data / 'offline', directory=True):
        return
    cutoff = (time.time() if now is None else now) - OFFLINE_DAYS * DAY
    for path in iter_plain_files(folder, OFFLINE_FILE):
        if path.stem in protected:
            continue
        try:
            if path.stat().st_mtime < cutoff:
                with path.open(encoding='utf-8') as file:
                    record = json.load(file)
                if isinstance(record, dict) and type(record.get('to')) in (float, int) and record['to'] < cutoff:
                    remove_data_file(path, '已存下播记录超过 60 天')
        except (OSError, ValueError):
            log.warning('无法核对下播记录，保留 %s', path.name)


def file_signature(path):
    if not is_plain(path):
        return None
    info = path.stat()
    return info.st_size, info.st_mtime_ns


def without_position(row):
    if not isinstance(row, dict):
        raise ValueError('弹幕记录不是对象')
    return {key: value for key, value in row.items() if key != 'i'}


def archive_rows(history, offline, end):
    if end is not None:
        if not is_plain(history):
            raise ValueError('缺少历史弹幕')
        with history.open(encoding='utf-8') as file:
            for line in file:
                yield without_position(json.loads(line))
    if is_plain(offline):
        with offline.open(encoding='utf-8') as file:
            record = json.load(file)
        if not isinstance(record, dict) or record.get('from') != (end or 0) or not isinstance(record.get('dm'), list):
            raise ValueError('下播存档不匹配')
        for row in record['dm']:
            yield without_position(row)


def prune_dmlog(data, room, indexed, protected):
    """旧日志必须逐条匹配历史和下播存档。房号单文件没有分段编号，留给人工核对。"""
    folder = data / 'history' / room
    offline_dir = data / 'offline' / room
    history_available = all(is_plain(p, directory=True) for p in (data / 'history', folder))
    offline_available = all(is_plain(p, directory=True) for p in (data / 'offline', offline_dir))
    pattern = re.compile(rf'{re.escape(room)}-(?P<sid>{SID})\.jsonl')
    unresolved = set()
    for path in iter_plain_files(data / 'dmlog', pattern):
        sid = pattern.fullmatch(path.name)['sid']
        if sid in protected:
            continue
        unresolved.add(sid)
        brief = indexed.get(sid)
        history = folder / f'{sid}.dm.jsonl'
        offline = offline_dir / f'{sid}.json' if offline_available else offline_dir / '.missing'
        try:
            end = None
            if brief:
                summary = folder / f'{sid}.json'
                if not history_available or not is_plain(summary):
                    continue
                with summary.open(encoding='utf-8') as file:
                    record = json.load(file)
                if not isinstance(record, dict) or record.get('brief') != brief or str(record.get('room_id')) != room:
                    continue
                end = brief['end']
            elif not is_plain(offline):
                continue

            files = [path]
            if end is not None:
                files.extend((summary, history))
            if is_plain(offline):
                files.append(offline)
            before = [file_signature(p) for p in files]
            missing = object()
            with path.open(encoding='utf-8') as file:
                original = (without_position(json.loads(line)) for line in file)
                archived = archive_rows(history, offline, end)
                matching = all(a == b for a, b in itertools.zip_longest(original, archived, fillvalue=missing))
            if matching and before == [file_signature(p) for p in files]:
                if remove_data_file(path, f'已逐条核对分段 {sid} 的归档弹幕'):
                    unresolved.remove(sid)
        except (OSError, ValueError, KeyError):
            log.warning('无法核对旧弹幕分段，保留 %s', path.name)
    return unresolved


def history_candidates(index, protected, now):
    cutoff = now - HISTORY_DAYS * DAY
    valid = [
        row for row in index
        if isinstance(row, dict) and isinstance(row.get('id'), str)
        and re.fullmatch(SID, row['id']) and type(row.get('start')) in (int, float)
        and type(row.get('end')) in (int, float)
    ]
    valid.sort(key=lambda row: (row['end'], row['id']), reverse=True)
    return [
        row for i, row in enumerate(valid)
        if row['id'] not in protected and (i >= HISTORY_MAX or row['end'] < cutoff)
    ][-HISTORY_EXPORT_BATCH:]


def export_history(data, cold, room, candidates):
    """在后台核对冷存档 ZIP。调用者随后核对原文件有没有变化，再从历史目录移出。"""
    folder = data / 'history' / room
    if not candidates or not all(is_plain(p, directory=True) for p in (data, data / 'history', folder)):
        return []
    ready = []
    for brief in candidates:
        sid = brief['id']
        summary = folder / f'{sid}.json'
        signature = file_signature(summary)
        if signature is None:
            continue
        try:
            with summary.open(encoding='utf-8') as file:
                body = json.load(file)
            if not isinstance(body, dict) or body.get('id') != sid or body.get('brief') != brief:
                continue
        except (OSError, ValueError):
            log.warning('历史总结无法核对，保留 %s', summary.name)
            continue
        files = {summary: signature}
        dm = folder / f'{sid}.dm.jsonl'
        if dm.exists() or dm.is_symlink():
            signature = file_signature(dm)
            if signature is None:
                continue
            files[dm] = signature
        ready.append((brief, files))
    if not ready:
        return []
    cold.mkdir(parents=True, exist_ok=True)
    if not all(is_plain(p, directory=True) for p in (cold.parent, cold)):
        raise OSError('历史冷存档目录不是普通目录')
    name = f"{room}-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:12]}.zip"
    archive = cold / name
    tmp = archive.with_suffix('.tmp')
    try:
        with zipfile.ZipFile(tmp, 'x', zipfile.ZIP_DEFLATED) as out:
            out.writestr('index.json', json.dumps([row for row, _ in ready], ensure_ascii=False))
            for _, files in ready:
                for path in files:
                    out.write(path, path.name)
        with zipfile.ZipFile(tmp) as check:
            if check.testzip() is not None:
                raise OSError('历史冷存档 ZIP 校验失败')
        ready = [(row, files) for row, files in ready
                 if all(file_signature(path) == signature for path, signature in files.items())]
        if ready:
            os.replace(tmp, archive)
            log.info('历史冷存档已校验：%s（%d 段）', archive.name, len(ready))
        return ready
    finally:
        tmp.unlink(missing_ok=True)


def prune_history_index(history, exported, protected, write_json):
    """后台压缩期间可能又存了历史，提交时重读索引并比对文件。"""
    index = history._index()
    by_id = {row['id']: row for row in index}
    ready = [
        (row['id'], files) for row, files in exported
        if row['id'] not in protected and by_id.get(row['id']) == row
        and all(file_signature(path) == signature for path, signature in files.items())
    ]
    if not ready:
        return
    ids = {sid for sid, _ in ready}
    write_json(history.index_file, [row for row in index if row['id'] not in ids])
    history._viewers, history._dm = None, (None, None)
    for _, files in ready:
        for path in files:
            remove_data_file(path, '已移入并校验历史冷存档')


# 每周的临时文件清理不接触存档、账号或备份；这些目录仍由各自既有的保留机制管理。
WEEKLY_PROTECTED = {'history', 'dmlog', 'offline', 'accounts'}


def safe_inside(root, path, directory=False):
    root, path = Path(root).absolute(), Path(path).absolute()
    try:
        relative = path.relative_to(root)
        if not is_plain(root, directory=True) or not path.resolve().is_relative_to(root.resolve()):
            return False
        parent = root
        for part in relative.parts[:-1]:
            parent = parent / part
            if not is_plain(parent, directory=True):
                return False
        return is_plain(path, directory=directory)
    except (OSError, ValueError):
        return False


def weekly_cleanup(root, write_json, now=None):
    root = Path(root).absolute()
    data = root / 'data'
    now = time.time() if now is None else now
    marker = data / 'maintenance.json'
    if not safe_inside(root, data, directory=True):
        return {'ran': False, 'files': 0, 'bytes': 0}
    last = 0
    if marker.exists():
        if not safe_inside(root, marker):
            return {'ran': False, 'files': 0, 'bytes': 0}
        try:
            with marker.open(encoding='utf-8') as f:
                saved = json.load(f)
            last = saved.get('last_cleanup', 0) if isinstance(saved, dict) else 0
            if type(last) not in (int, float):
                last = 0
        except (OSError, ValueError):
            pass
    if now - last < 7 * DAY:
        return {'ran': False, 'files': 0, 'bytes': 0}
    removed, freed = 0, 0

    def delete(path, age, reason):
        nonlocal removed, freed
        if not safe_inside(root, path):
            return
        info = path.stat()
        if now - info.st_mtime <= age:
            return
        if remove_data_file(path, reason):
            removed += 1
            freed += info.st_size

    # 只走 data 中允许的普通目录，明确排除不能触碰的四类原始数据。
    pending = [data]
    while pending:
        folder = pending.pop()
        if not safe_inside(root, folder, directory=True):
            continue
        for path in folder.iterdir():
            if path.name.casefold() in WEEKLY_PROTECTED or path.name.casefold() in {'static', '备份'}:
                continue
            if is_plain(path, directory=True):
                pending.append(path)
            elif path.suffix.lower() == '.tmp':
                delete(path, DAY, '每周清理：临时文件超过 1 天')
            elif folder == data / 'imgcache' and re.fullmatch(r'[0-9a-f]{40}\.webp', path.name):
                delete(path, 30 * DAY, '每周清理：图片缓存超过 30 天')
    for path in root.iterdir():
        if re.fullmatch(r'(?:demo|test).*\.log', path.name, re.I):
            delete(path, 14 * DAY, '每周清理：演示或测试日志超过 14 天')
    # 固定一个状态文件；记录成功完成的时间，重启不会马上重复清理。
    write_json(str(marker), {'last_cleanup': now, 'files': removed, 'bytes': freed})
    log.info('每周清理完成：删除 %d 个文件，腾出 %d 字节', removed, freed)
    return {'ran': True, 'files': removed, 'bytes': freed}
