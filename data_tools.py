"""数据管理（2026-11-28 用户：一键管理、更方便清理，别让数据越堆越多）。

- report()：data 和「备份」里每一类占多少（图片缓存、浏览器缓存、备份、整场弹幕、历史场次、其它）
- clean()：按类清理，只清缓存和用户点名要清的，历史场次的数字、送礼榜、观众档案都不动
- merge_sessions()：把被误切成两场的历史合成一场
都只在雾幕自己的文件夹里动，不跟链接（快捷方式、联接）走出去。
"""
import gzip
import json
import os
import re
import stat
import time

# 浏览器自己的缓存目录名（软件窗口 data/webview、抖音 / 网易云登录用的浏览器）：清掉不影响登录和设置
BROWSER_DIRS = ('webview', 'music-browser', 'douyin-browser', 'desktop-browser')
CACHE_NAMES = {'Cache', 'Code Cache', 'GPUCache', 'DawnCache', 'DawnGraphiteCache', 'DawnWebGPUCache', 'GrShaderCache',
               'ShaderCache', 'GraphiteDawnCache', 'CacheStorage', 'ScriptCache', 'Crashpad', 'BrowserMetrics',
               'component_crx_cache', 'extensions_crx_cache', 'Safe Browsing', 'optimization_guide_model_store', 'WasmTtsEngine',
               # 这几个浏览器打开时都带着 --disable-extensions，扩展和 Edge 自带的购物、钱包这些用不上（以前同步进来的能有几百 MB）
               'Extensions', 'Local Extension Settings', 'Extension State', 'ProvenanceData', 'Edge Shopping', 'Edge Wallet',
               'Edge Entity Extraction', 'Subresource Filter', 'Service Worker'}
SID_RE = re.compile(r'^\d{8}-\d{4}(?:-[0-9a-f]{12})?$')
DM_RE = re.compile(r'^(\d{8}-\d{4}(?:-[0-9a-f]{12})?)\.dm\.jsonl(?:\.gz)?$')
BACKUP_RE = re.compile(r'^data-\d{8}(?:-\d{6}-[\w-]{1,12})?\.zip$')


def plain(path, directory=False):
    """不是链接、不是联接（清理不会跨出雾幕的文件夹）"""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        return False
    return stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)


def walk_size(root, only=None):
    """一个文件夹多大：(字节, 文件数)。only(相对路径的各段) 返回 True 的才算"""
    total = files = 0
    if not plain(root, directory=True):
        return 0, 0
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if plain(os.path.join(base, d), directory=True)]
        rel = os.path.relpath(base, root).split(os.sep)
        if only and not only(rel):
            continue
        for n in names:
            p = os.path.join(base, n)
            try:
                if plain(p):
                    total += os.path.getsize(p)
                    files += 1
            except OSError:
                pass
    return total, files


def in_cache(parts):
    return any(p in CACHE_NAMES for p in parts)


def backups(app_dir):
    d = os.path.join(app_dir, '备份', '数据')
    try:
        names = [n for n in os.listdir(d) if BACKUP_RE.fullmatch(n) and plain(os.path.join(d, n))]
    except OSError:
        return d, []
    return d, sorted(names, key=lambda n: os.path.getmtime(os.path.join(d, n)), reverse=True)


def history_dirs(data):
    root = os.path.join(data, 'history')
    if not plain(root, directory=True):
        return []
    return [os.path.join(root, r) for r in os.listdir(root) if plain(os.path.join(root, r), directory=True)]


def report(app_dir):
    """每一类占多少。返回 [{key, name, bytes, files, desc, clean}]，再加一行合计"""
    data = os.path.join(app_dir, 'data')
    rows = []
    img = walk_size(os.path.join(data, 'imgcache'))
    rows.append({'key': 'img', 'name': '图片缓存', 'bytes': img[0], 'files': img[1], 'clean': True,
                 'desc': '头像、礼物图标存在电脑上，下次打开快。清掉以后用到会再下载'})
    br = [0, 0]
    for d in BROWSER_DIRS:
        s = walk_size(os.path.join(data, d), only=in_cache)
        br[0] += s[0]
        br[1] += s[1]
    rows.append({'key': 'browser', 'name': '浏览器缓存', 'bytes': br[0], 'files': br[1], 'clean': True,
                 'desc': '软件窗口、抖音、网易云登录用的浏览器自己存的缓存。清掉不影响登录和设置'})
    bdir, names = backups(app_dir)
    bsize = sum(os.path.getsize(os.path.join(bdir, n)) for n in names)
    rows.append({'key': 'backup', 'name': '数据备份', 'bytes': bsize, 'files': len(names), 'clean': True,
                 'desc': '每天自动备份一份，还有手动、更新前的。可以只留最近几份'})
    dm = [0, 0]
    oldest = 0
    for h in history_dirs(data):
        for n in os.listdir(h):
            m = DM_RE.match(n)
            if m and plain(os.path.join(h, n)):
                dm[0] += os.path.getsize(os.path.join(h, n))
                dm[1] += 1
                t = sid_time(m.group(1))
                oldest = min(oldest or t, t)
    rows.append({'key': 'dm', 'name': '历史里的整场弹幕', 'bytes': dm[0], 'files': dm[1], 'clean': True, 'oldest': oldest,
                 'desc': '每场的逐条弹幕。清掉以后那场的数字、送礼榜、SC、上舰都还在，只是看不到逐条弹幕'})
    hs = [0, 0]
    for h in history_dirs(data):
        s = walk_size(h)
        hs[0] += s[0]
        hs[1] += s[1]
    rows.append({'key': 'history', 'name': '历史场次', 'bytes': max(0, hs[0] - dm[0]), 'files': max(0, hs[1] - dm[1]), 'clean': False,
                 'desc': '每场的数字、送礼榜、上舰、SC。很小，一直留着；不要的场次可以在「历史」里删'})
    allsize = walk_size(data)
    other = max(0, allsize[0] - img[0] - br[0] - hs[0])
    rows.append({'key': 'other', 'name': '其它', 'bytes': other, 'files': 0, 'clean': False,
                 'desc': '设置、本场数据、观众备注、曲库、浏览器里的登录信息这些，都要留着'})
    rows.append({'key': 'total', 'name': '一共', 'bytes': allsize[0] + bsize, 'files': allsize[1] + len(names), 'clean': False, 'desc': ''})
    return rows


def sid_time(sid):
    try:
        return int(time.mktime(time.strptime(sid[:13], '%Y%m%d-%H%M')))
    except ValueError:
        return 0


def remove_tree_files(root, only):
    """删 root 下 only(相对路径各段) 为真的文件夹里的文件；正在用（锁着）的跳过。返回 (腾出字节, 删掉几个, 跳过几个)"""
    freed = n = skipped = 0
    if not plain(root, directory=True):
        return 0, 0, 0
    for base, dirs, names in os.walk(root, topdown=False):
        rel = os.path.relpath(base, root).split(os.sep)
        if not only(rel):
            continue
        for name in names:
            p = os.path.join(base, name)
            if not plain(p):
                continue
            try:
                size = os.path.getsize(p)
                os.remove(p)
                freed += size
                n += 1
            except OSError:
                skipped += 1
        if base != root:
            try:
                os.rmdir(base)  # 空了的文件夹顺手删掉（不空就算了）
            except OSError:
                pass
    return freed, n, skipped


def clean(app_dir, key, keep=3, days=90, protect=()):
    """清一类。keep：备份留几份；days：多少天以前的整场弹幕；protect：现在这场的编号（不删）。返回 (腾出字节, 说明)"""
    data = os.path.join(app_dir, 'data')
    if key == 'img':
        freed, n, skipped = remove_tree_files(os.path.join(data, 'imgcache'), lambda rel: True)
        return freed, f'删了 {n} 张缓存的图' + (f'，{skipped} 张正在用没删' if skipped else '')
    if key == 'browser':
        freed = n = skipped = 0
        for d in BROWSER_DIRS:
            f, c, s = remove_tree_files(os.path.join(data, d), in_cache)
            freed, n, skipped = freed + f, n + c, skipped + s
        return freed, f'删了 {n} 个缓存文件' + (f'，{skipped} 个正在用没删（关掉雾幕再清能清干净）' if skipped else '')
    if key == 'backup':
        keep = max(1, int(keep))
        bdir, names = backups(app_dir)
        freed = 0
        for name in names[keep:]:
            p = os.path.join(bdir, name)
            try:
                freed += os.path.getsize(p)
                os.remove(p)
            except OSError:
                pass
        return freed, f'只留了最近 {min(keep, len(names))} 份备份'
    if key == 'dm':
        cutoff = time.time() - max(0, int(days)) * 86400
        freed = n = 0
        for h in history_dirs(data):
            for name in os.listdir(h):
                m = DM_RE.match(name)
                p = os.path.join(h, name)
                if not m or m.group(1) in protect or not plain(p) or sid_time(m.group(1)) > cutoff:
                    continue
                try:
                    freed += os.path.getsize(p)
                    os.remove(p)
                    n += 1
                except OSError:
                    pass
        return freed, f'清掉了 {n} 场的逐条弹幕（{int(days)} 天以前的）'
    raise ValueError('这一类不能清')


def total_size(app_dir):
    """data 加备份一共多大（占用提醒用）"""
    _, names = backups(app_dir)
    bdir = os.path.join(app_dir, '备份', '数据')
    return walk_size(os.path.join(app_dir, 'data'))[0] + sum(os.path.getsize(os.path.join(bdir, n)) for n in names)


# ---------- 两场合成一场 ----------
def _merge_by(rows_a, rows_b, key, add, keep_last=()):
    out = {}
    order = []
    for r in list(rows_a or []) + list(rows_b or []):
        if not isinstance(r, dict) or r.get(key) is None:
            continue
        k = r[key]
        if k not in out:
            out[k] = dict(r)
            order.append(k)
            continue
        cur = out[k]
        for f in add:
            if isinstance(r.get(f), (int, float)):
                cur[f] = round((cur.get(f) or 0) + r[f], 2)
        for f in keep_last:
            if r.get(f):
                cur[f] = r[f]
    return [out[k] for k in order]


def merge_summaries(a, b):
    """两场的总结合成一场（a 是先开始的那场，用它的编号）"""
    if b['start'] < a['start']:
        a, b = b, a
    flow = {k: round((a.get('flow') or {}).get(k, 0) + (b.get('flow') or {}).get(k, 0), 2)
            for k in set(a.get('flow') or {}) | set(b.get('flow') or {})}
    total = round(sum(flow.values()), 2)
    va = {v[0]: v for v in a.get('viewers') or [] if isinstance(v, list) and v}
    vb = {v[0]: v for v in b.get('viewers') or [] if isinstance(v, list) and v}
    viewers = []
    for uid in list(va) + [u for u in vb if u not in va]:
        x, y = va.get(uid), vb.get(uid)
        if x and y:
            viewers.append([uid, y[1], x[2] + y[2], round(x[3] + y[3], 2), x[4] + y[4]])
        else:
            viewers.append(list(x or y))
    overlap = len(set(va) & set(vb))
    rank = _merge_by(a.get('rank'), b.get('rank'), 'uid', ('spend', 'dm'), keep_last=('name', 'face'))
    for r in rank:
        g = [x.get('guard') or 0 for x in (a.get('rank') or []) + (b.get('rank') or []) if isinstance(x, dict) and x.get('uid') == r['uid']]
        r['guard'] = min([x for x in g if x] or [0])
    rank = sorted(rank, key=lambda r: -(r.get('spend') or 0))[:100]
    gifts = sorted(_merge_by(a.get('gift_stats'), b.get('gift_stats'), 'name', ('num', 'yuan', 'count')),
                   key=lambda g: -(g.get('yuan') or 0))
    sa, sb = a.get('stats') or {}, b.get('stats') or {}
    stats = {k: max(sa.get(k) or 0, sb.get(k) or 0) if isinstance(sa.get(k, sb.get(k)), (int, float)) else (sb.get(k) or sa.get(k))
             for k in set(sa) | set(sb)}
    brief = {'id': a['id'], 'title': a.get('title') or b.get('title') or '', 'start': a['start'], 'end': max(a.get('end', 0), b.get('end', 0)),
             'total': total, 'income': round(total / 2, 2), 'flow': flow,
             'dm_total': (a.get('dm_total') or 0) + (b.get('dm_total') or 0),
             'user_count': max(len(viewers), (a.get('user_count') or 0) + (b.get('user_count') or 0) - overlap),
             'sc_count': (a.get('sc_count') or 0) + (b.get('sc_count') or 0),
             'guard_count': (a.get('guard_count') or 0) + (b.get('guard_count') or 0),
             'peak_online': max(a.get('peak_online') or 0, b.get('peak_online') or 0), 'reason': b.get('reason') or a.get('reason') or ''}
    out = {**a, **brief, 'brief': brief, 'stats': stats,
           'outages': (a.get('outages') or []) + (b.get('outages') or []),
           'rank': rank, 'scs': (a.get('scs') or []) + (b.get('scs') or []), 'guards': (a.get('guards') or []) + (b.get('guards') or []),
           'gift_stats': gifts, 'big_gifts': (a.get('big_gifts') or []) + (b.get('big_gifts') or []), 'viewers': viewers,
           'merged': sorted(set((a.get('merged') or []) + (b.get('merged') or []) + [b['id']]))}
    if 'dm_log_count' in a or 'dm_log_count' in b:
        out['dm_log_count'] = (a.get('dm_log_count') or 0) + (b.get('dm_log_count') or 0)
    return out


def read_dm(folder, sid):
    """一场的逐条弹幕（.dm.jsonl 或压缩过的 .dm.jsonl.gz）；没有返回 []"""
    rows = []
    for path, opener in ((os.path.join(folder, sid + '.dm.jsonl'), open), (os.path.join(folder, sid + '.dm.jsonl.gz'), gzip.open)):
        if plain(path):
            with opener(path, 'rt', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except ValueError:
                            pass
            break
    return rows


def merge_sessions(folder, sid_a, sid_b, write_json):
    """把 folder（data/history/房间号）里的两场合成一场：总结合并、逐条弹幕接起来，留先开始那场的编号，另一场删掉。返回合好的总结"""
    if not (SID_RE.match(sid_a) and SID_RE.match(sid_b)) or sid_a == sid_b:
        raise ValueError('场次编号不对')
    with open(os.path.join(folder, sid_a + '.json'), encoding='utf-8') as f:
        a = json.load(f)
    with open(os.path.join(folder, sid_b + '.json'), encoding='utf-8') as f:
        b = json.load(f)
    if a.get('room_id') != b.get('room_id'):
        raise ValueError('不是同一个直播间的，不能合')
    m = merge_summaries(a, b)
    first, second = (a, b) if m['id'] == a['id'] else (b, a)
    rows = read_dm(folder, first['id']) + read_dm(folder, second['id'])
    if rows:
        tmp = os.path.join(folder, first['id'] + '.dm.jsonl.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        os.replace(tmp, os.path.join(folder, first['id'] + '.dm.jsonl'))
        try:
            os.remove(os.path.join(folder, first['id'] + '.dm.jsonl.gz'))
        except OSError:
            pass
    write_json(os.path.join(folder, first['id'] + '.json'), m)
    index_file = os.path.join(folder, 'index.json')
    try:
        with open(index_file, encoding='utf-8') as f:
            idx = json.load(f)
    except (OSError, ValueError):
        idx = []
    idx = [x for x in idx if isinstance(x, dict) and x.get('id') not in (a['id'], b['id'])] + [m['brief']]
    write_json(index_file, idx)
    for p in (second['id'] + '.json', second['id'] + '.dm.jsonl', second['id'] + '.dm.jsonl.gz'):
        try:
            os.remove(os.path.join(folder, p))
        except OSError:
            pass
    return m

