"""公开访问配额在内存中维护，失败只记固定原因，避免泄露 IP 或刷出大量日志。"""
import collections
import ipaddress
import logging
import time
from urllib.parse import urlsplit

log = logging.getLogger('xiaowu')


def client_ip(request, public_url):
    peer = request.remote or 'unknown'
    # cloudflared 在本机回环代理；远端直连即使伪造 CF 头，也只能记在其真实对端名下。
    if (peer in ('127.0.0.1', '::1') and request.host.lower() == urlsplit(public_url).netloc.lower()
            and request.headers.get('Cf-Ray') and request.headers.get('CF-Connecting-IP')):
        try:
            return str(ipaddress.ip_address(request.headers['CF-Connecting-IP']))
        except ValueError:
            pass
    try:
        return str(ipaddress.ip_address(peer))
    except ValueError:
        return 'unknown'


class PublicLimits:
    def __init__(self, total=200, per_ip=5, connect_rate=20, http_rate=600, gequ_rate=3000,
                 obs_total=50, obs_ip=10, max_ips=10000):
        self.total, self.per_ip, self.connect_rate = total, per_ip, connect_rate
        self.http_rate, self.gequ_rate = http_rate, gequ_rate
        self.obs_total, self.obs_ip, self.max_ips = obs_total, obs_ip, max_ips
        self.active = {}
        self.windows = collections.OrderedDict()
        self.rejected = collections.Counter()
        self.last_log = 0

    def reject(self, reason):
        self.rejected[reason] += 1
        return reason

    def report(self, now=None):
        now = time.monotonic() if now is None else now
        self.prune(now)
        if now - self.last_log >= 60 and self.rejected:
            for reason, count in self.rejected.items():
                log.warning('公开访问已限制：%s', reason, extra={'error_count': count})
            self.rejected.clear()
            self.last_log = now

    def prune(self, now):
        while self.windows:
            key, row = next(iter(self.windows.items()))
            if now - row[0] < 60:
                break
            self.windows.pop(key)

    def rate(self, ip, kind, limit, now):
        self.prune(now)
        key = (ip, kind)
        row = self.windows.get(key)
        if row is None:
            if len(self.windows) >= self.max_ips:
                return False
            row = [now, collections.deque(), 0]
            self.windows[key] = row
        row[0] = now
        self.windows.move_to_end(key)
        buckets = row[1]
        while buckets and now - buckets[0][0] >= 60:
            row[2] -= buckets.popleft()[1]
        if row[2] >= limit:
            return False
        # 每秒合并计数，单个 IP 最多 61 个桶，不随访问量增长。
        if buckets and int(buckets[-1][0]) == int(now):
            buckets[-1][0] = now
            buckets[-1][1] += 1
        else:
            buckets.append([now, 1])
        row[2] += 1
        return True

    def reserve(self, ticket, ip, kind='public', exempt=False, now=None):
        if exempt:
            return ''
        now = time.monotonic() if now is None else now
        if kind == 'public' and not self.rate(ip, 'connect', self.connect_rate, now):
            return self.reject('连接太频繁，请一分钟后再试')
        rows = [p for p, k in self.active.values() if k == kind]
        total, per_ip = (self.obs_total, self.obs_ip) if kind == 'obs' else (self.total, self.per_ip)
        if len(rows) >= total:
            return self.reject('观看人数已满，请稍后再试' if kind == 'public' else 'OBS 连接已满，请关闭多余页面')
        if rows.count(ip) >= per_ip:
            return self.reject('这个网络打开的页面太多，请先关掉一些')
        self.active[ticket] = (ip, kind)
        return ''

    def release(self, ticket):
        self.active.pop(ticket, None)

    def http(self, ip, path, exempt=False, now=None):
        if exempt or path == '/api/ping':
            return ''
        now = time.monotonic() if now is None else now
        gequ = path in ('/gequ.html', '/gequ.json') or path.startswith('/gequ/')
        if not self.rate(ip, 'gequ' if gequ else 'http', self.gequ_rate if gequ else self.http_rate, now):
            return self.reject('访问太频繁，请一分钟后再试')
        return ''

    def snapshot(self):
        return {'public': sum(kind == 'public' for _, kind in self.active.values()),
                'obs': sum(kind == 'obs' for _, kind in self.active.values()),
                'public_limit': self.total, 'obs_limit': self.obs_total}
