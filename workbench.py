"""歌曲资料和待回应任务。与直播间数据分开保存，清零本场不会清空曲库或待办。"""
import copy
import time
from urllib.parse import urlsplit


def trusted_origin(origin, host, public_url, port):
    """浏览器来源只接受配置的站点或本机端口；不信任任意 Host 的同源声明。"""
    try:
        u = urlsplit(origin)
        public = urlsplit(public_url)
        allowed = {f'http://127.0.0.1:{port}', f'http://localhost:{port}', f'http://[::1]:{port}'}
        if public.scheme in ('http', 'https') and public.netloc:
            allowed.add(f'{public.scheme}://{public.netloc}'.lower())
        normalized = f'{u.scheme}://{u.netloc}'.lower()
        hosts = {urlsplit(x).netloc for x in allowed}
        return bool(origin and not u.path and not u.query and not u.fragment and
                    normalized in allowed and host.lower() in hosts)
    except (ValueError, AttributeError):
        return False


def clean_song(row):
    if not isinstance(row, dict):
        raise ValueError('每首歌需要包含歌名')
    name = str(row.get('name', '')).strip()[:80]
    if not name:
        raise ValueError('请填写歌名')
    tags = row.get('tags', [])
    if isinstance(tags, str):
        tags = tags.replace('，', ',').split(',')
    if not isinstance(tags, list):
        raise ValueError('标签请用逗号分隔')
    link = str(row.get('backing', '')).strip()[:1500]
    if link and urlsplit(link).scheme not in ('https', 'http'):
        raise ValueError('伴奏链接请填写 http 或 https 地址')
    level = str(row.get('level', '待整理'))
    if level not in ('待整理', '练习中', '熟悉', '拿手'):
        raise ValueError('请选择有效的熟练度')
    out = {'name': name, 'artist': str(row.get('artist', '')).strip()[:80],
            'tags': list(dict.fromkeys(str(t).strip()[:24] for t in tags if str(t).strip()))[:12],
            'level': level, 'key': str(row.get('key', '')).strip()[:24], 'backing': link,
            'available': row.get('available', True) is not False,
            'note': str(row.get('note', '')).strip()[:1000]}
    # 歌词 / 谱子链接：只有填了这一项才更新，导入表格没有这一列时不会把已填的歌词清掉
    if 'lyrics' in row:
        out['lyrics'] = str(row.get('lyrics') or '').strip()[:8000]
    return out


class ResponseQueue:
    def __init__(self, path, read_json, write_json):
        self.path, self.write_json = path, write_json
        self.data = read_json(path) if path else {}
        if not isinstance(self.data, dict):
            self.data = {}
        self.dirty = False

    def save(self):
        if self.path and self.dirty:
            self.write_json(self.path, self.data)
            self.dirty = False

    def upsert(self, kind, item, session):
        key = f"{session}:{kind}:{item.get('id') or str(item.get('uid')) + '-' + str(item.get('t'))}"
        prev = self.data.get(key, {})
        text = (item.get('text', '') if kind == 'sc' else
                f"{item.get('gift', '')} ×{item.get('num', 1)}" if kind == 'gift' else
                f"开通{item.get('level_name', '大航海')} ×{item.get('num', 1)}")
        row = {**prev, 'id': key, 'kind': kind, 'source_id': str(item.get('id', '')),
               'session': session, 'name': item.get('name', ''), 'uid': item.get('uid', 0),
               'text': text, 'amount': item.get('price', item.get('yuan', 0)),
               't': item.get('t', int(time.time())), 'done': prev.get('done', False),
               'read': prev.get('read', False)}
        if prev and prev.get('text') != text and prev.get('done'):
            row['done'] = False  # 已答谢后又有连击，重新提示
        if prev != row:
            self.data[key] = row
            self.dirty = True
        return row

    def rows(self):
        return sorted(self.data.values(), key=lambda x: (x['done'], -x['t']))

    def command(self, cmd, ids, value):
        if not isinstance(ids, list) or len(ids) > 3000 or not isinstance(value, bool):
            raise ValueError('无效的回应操作')
        if not all(isinstance(key, str) for key in ids):
            raise ValueError('无效的回应编号')
        old = {key: copy.copy(self.data[key]) for key in ids if key in self.data}
        old_dirty = self.dirty
        field = 'read' if cmd == 'response_read' else 'done'
        for key in ids:
            if key in self.data:
                self.data[key][field] = value
                self.data[key]['updated'] = int(time.time())
                self.dirty = True
        try:
            self.save()
        except OSError:
            self.data.update(old)
            self.dirty = old_dirty
            raise


def read_object(path):
    import json
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return {}
