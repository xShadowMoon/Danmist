"""管理链接只存摘要；先持久化再生效，撤销旧链接后重启不会重新导入。"""
import copy
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from urllib.parse import urlencode

DAY = 86400
MAX_ACTIVE = 10
MAX_RECORDS = 512
MAX_LEGACY = 64
log = logging.getLogger('xiaowu')


def redact_admin(text):
    return re.sub(r"(?i)(?:[\"']?)(?:admin(?:[_-]key)?|xwadmin)(?:[\"']?)\s*[=:]\s*(?:\"[^\"]*\"|'[^']*'|[^\s&;,}\"']+)",
                  'admin=[隐藏]', str(text))


class AdminSafeFormatter(logging.Formatter):
    def format(self, record):
        # 格式化后再遮盖，异常堆栈里的查询参数和 cookie 同样不能泄露密钥。
        return redact_admin(super().format(record))


def digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


class AdminLinks:
    def __init__(self, path, writer, legacy='', now=None):
        self.path, self.writer = path, writer
        self.data = {'links': [], 'legacy': []}
        self.failed = False
        self.dirty = False
        if path:
            try:
                with open(path, encoding='utf-8') as f:
                    data = json.load(f)
                if (not isinstance(data, dict) or not isinstance(data.get('links'), list)
                        or not isinstance(data.get('legacy'), list) or len(data['links']) > MAX_RECORDS
                        or len(data['legacy']) > MAX_LEGACY):
                    raise ValueError()
                for row in data['links']:
                    if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                            or not re.fullmatch(r'[0-9a-f]{32}', row['id'])
                            or not isinstance(row.get('hash'), str) or not re.fullmatch(r'[0-9a-f]{64}', row['hash'])
                            or not isinstance(row.get('name'), str) or len(row['name']) > 12
                            or any(type(row.get(k)) not in (int, float) or not 0 <= row[k] <= 4102444800
                                   for k in ('created_at', 'expires_at', 'last_used_at', 'revoked_at'))):
                        raise ValueError()
                if (len({r['id'] for r in data['links']}) != len(data['links'])
                        or any(not isinstance(h, str) or not re.fullmatch(r'[0-9a-f]{64}', h) for h in data['legacy'])):
                    raise ValueError()
                self.data = data
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError):
                # 损坏时宁可只允许本机进入，也不能让已作废的旧密钥重新有效。
                self.failed = True
                log.error('管理链接文件无法读取，请在本机检查或恢复备份')
        now = time.time() if now is None else now
        if legacy and not self.failed:
            hashed = digest(legacy)
            if not any(hmac.compare_digest(hashed, h) for h in self.data['legacy']):
                rows = self.cleaned(now)
                if len(self.data['legacy']) >= MAX_LEGACY or sum(self.valid(r, now) for r in rows) >= MAX_ACTIVE:
                    log.error('旧管理链接导入已达上限，请从本机整理链接')
                    return
                row = self.row('旧管理链接', 0, now, hashed)
                data = {'links': rows + [row], 'legacy': self.data['legacy'] + [hashed]}
                try:
                    self.commit(data)
                except OSError:
                    self.failed = True
                    log.error('管理链接文件无法保存，请从本机检查磁盘和权限')

    @staticmethod
    def valid(row, now):
        return not row['revoked_at'] and (not row['expires_at'] or now < row['expires_at'])

    @staticmethod
    def row(name, days, now, hashed):
        return {'id': uuid.uuid4().hex, 'hash': hashed, 'name': name, 'created_at': int(now),
                'expires_at': int(now + days * DAY) if days else 0, 'last_used_at': 0, 'revoked_at': 0}

    def commit(self, data):
        if self.failed:
            raise ValueError('管理链接文件无法读取，请先恢复')
        if self.path:
            self.writer(self.path, data)
        self.data, self.dirty = data, False

    def cleaned(self, now):
        return [r for r in self.data['links'] if not (
            (r['revoked_at'] or r['expires_at']) and now - (r['revoked_at'] or r['expires_at']) > 30 * DAY)]

    def active(self, link_id, now=None):
        now = time.time() if now is None else now
        return not self.failed and any(r['id'] == link_id and self.valid(r, now) for r in self.data['links'])

    def authenticate(self, token, now=None):
        if self.failed or not isinstance(token, str) or not token or len(token) > 512:
            return None
        now = time.time() if now is None else now
        hashed = digest(token)
        found = None
        for row in self.data['links']:
            if hmac.compare_digest(hashed, row['hash']) and self.valid(row, now):
                found = row
        if found is not None:
            if now - found['last_used_at'] >= 60:
                found['last_used_at'] = int(now)
                self.dirty = True
            return found['id']
        return None

    def listing(self, current=None, now=None):
        now = time.time() if now is None else now
        return [{**{k: v for k, v in r.items() if k != 'hash'}, 'current': r['id'] == current,
                 'active': self.valid(r, now)} for r in self.cleaned(now)]

    def create(self, name='', days=30, replace=False, now=None, host=False):
        now = time.time() if now is None else now
        if not isinstance(name, str) or len(name) > 12 or type(days) is not int or days not in (0, 1, 7, 30):
            raise ValueError('链接名字或有效期不对')
        data = copy.deepcopy(self.data)
        data['links'] = copy.deepcopy(self.cleaned(now))
        if replace:
            for row in data['links']:
                if self.valid(row, now):
                    row['revoked_at'] = int(now)
        if sum(self.valid(r, now) for r in data['links']) >= MAX_ACTIVE:
            raise ValueError('有效管理链接最多 10 把，请先作废旧链接')
        if len(data['links']) >= MAX_RECORDS:
            raise ValueError('近期管理链接过多，请稍后再建')
        token = secrets.token_urlsafe(32)
        row = self.row(name.strip(), days, now, digest(token))
        if host:  # 主播专属：页面里不显示后台的东西，并记下每次打开（2026-11-18）
            row.update(host=True, opens=0, open_log=[], seen_at=0)
        data['links'].append(row)
        self.commit(data)
        return row['id'], token

    def revoke(self, link_id, now=None):
        now = time.time() if now is None else now
        data = copy.deepcopy(self.data)
        row = next((r for r in data['links'] if r['id'] == link_id), None)
        if row is None:
            raise ValueError('管理链接不存在')
        row['revoked_at'] = row['revoked_at'] or int(now)
        self.commit(data)

    def open_delete(self, link_id, t):
        """删掉主播专属链接的一条打开记录（2026-11-19：自己测试时打开的那次不算）。全删光了「用过」也清掉。"""
        data = copy.deepcopy(self.data)
        row = next((r for r in data['links'] if r['id'] == link_id and r.get('host')), None)
        if row is None:
            raise ValueError('主播专属链接不存在')
        log_ = [x for x in (row.get('open_log') or []) if int(x) != int(t)]
        src = [o for o in (row.get('open_src') or []) if int(o.get('t', 0)) != int(t)]
        if len(log_) == len(row.get('open_log') or []) and len(src) == len(row.get('open_src') or []):
            raise ValueError('这条记录已经没有了')
        row['open_log'], row['open_src'] = log_, src
        row['opens'] = max(0, int(row.get('opens', 0)) - 1)
        if not log_:
            row['opens'], row['last_used_at'], row['seen_at'] = 0, 0, 0
        self.commit(data)

    def is_host(self, link_id):
        return any(r['id'] == link_id and r.get('host') for r in self.data['links'])

    def record_open(self, link_id, now=None, where=None):
        """主播专属链接被打开：距离上次连着的时候超过 10 分钟才算新打开一次（断线重连不算）。
        where（2026-11-19）：这次从哪打开的 {ip, cc 国家代码, region, city, dev 设备}，记在 open_src 里（留最近 50 次）。"""
        now = time.time() if now is None else now
        row = next((r for r in self.data['links'] if r['id'] == link_id and r.get('host')), None)
        if row is None:
            return
        if now - row.get('seen_at', 0) > 600:
            row['opens'] = int(row.get('opens', 0)) + 1
            row['open_log'] = (list(row.get('open_log') or []) + [int(now)])[-50:]
            if isinstance(where, dict):
                src = {'t': int(now), **{k: str(where.get(k) or '')[:64] for k in ('ip', 'cc', 'region', 'city', 'dev')}}
                row['open_src'] = (list(row.get('open_src') or []) + [src])[-50:]
        row['seen_at'] = int(now)
        self.dirty = True

    def touch(self, link_id, now=None):
        row = next((r for r in self.data['links'] if r['id'] == link_id and r.get('host')), None)
        if row is not None:
            row['seen_at'] = int(time.time() if now is None else now)
            self.dirty = True

    def maintain(self, now=None):
        now = time.time() if now is None else now
        rows = self.cleaned(now)
        if self.dirty or len(rows) != len(self.data['links']):
            self.commit({**self.data, 'links': rows})

    def command(self, command, base_url, current=None, access_key=''):
        cmd = command['cmd']
        if cmd == 'admin_link_list':
            return {'links': self.listing(current)}
        if cmd == 'admin_link_revoke':
            self.revoke(command['id'])
            return {'links': self.listing(current)}
        if cmd == 'admin_link_open_del':
            self.open_delete(command['id'], command['t'])
            return {'links': self.listing(current)}
        link_id, token = self.create(command.get('name', ''), command.get('days', 30), cmd == 'admin_link_rotate',
                                     host=cmd == 'admin_link_create' and command.get('host') is True)
        # 明文只用于这次响应，不进入列表、日志或持久数据。
        query = {'admin': token}
        if access_key:
            query['key'] = access_key
        path = '/host?' if self.is_host(link_id) else '/?'  # 主播专属链接用 /host
        return {'id': link_id, 'url': base_url.rstrip('/') + path + urlencode(query),
                'links': self.listing(current)}
