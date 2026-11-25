"""有界错误记录与每日汇总；记录前脱敏，发送失败保留当天待重试状态。"""
import asyncio
from admin_links import redact_admin
import copy
import datetime as dt
import hashlib
import json
import logging
import math
import re
import sys
import threading
import time

DAY = 86400
MAX_ERRORS = 2000


def redact(value):
    text = redact_admin(value)
    text = re.sub(r'https?://[^\s<>\"\']+', '[网址已隐藏]', text, flags=re.I)
    text = re.sub(r'(?im)(?:set-cookie|cookie|authorization)\s*[=:：]\s*[^\r\n]+', '[凭据已隐藏]', text)
    text = re.sub(r'(?i)\bBearer\s+\S+', 'Bearer [隐藏]', text)
    text = re.sub(r"(?i)(?:[\"']?)(?:[a-z_]*token|[a-z_]*secret|password|passwd|api[_-]?key|sessdata|bili_jct|dedeuserid|cookie|authorization)(?:[\"']?)\s*(?:[=:：]|\s)\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)", '[凭据已隐藏]', text)
    return ' '.join(text.split())[:500]


def hour_start(now):
    return int(dt.datetime.fromtimestamp(now).replace(minute=0, second=0, microsecond=0).timestamp())


class ErrorJournal(logging.Handler):
    def __init__(self, path, marker, writer, hour=10):
        super().__init__(logging.WARNING)
        self.path, self.marker, self.writer, self.hour = path, marker, writer, hour
        self.rows, self.last_day = [], ''
        self.dirty = self.marker_dirty = False
        self.guard = threading.RLock()
        self.sending = False
        for file, kind in ((path, 'rows'), (marker, 'marker')):
            if not file:
                continue
            try:
                with open(file, encoding='utf-8') as f:
                    data = json.load(f)
                if kind == 'rows' and isinstance(data, list):
                    for r in data[-MAX_ERRORS:]:
                        if (isinstance(r, dict) and all(type(r.get(k)) in (int, float) for k in ('hour', 'first', 'last', 'count'))
                                and all(math.isfinite(r[k]) for k in ('hour', 'first', 'last', 'count'))
                                and r.get('level') in ('WARNING', 'ERROR', 'CRITICAL')
                                and 0 < r['count'] <= 10**12 and all(isinstance(r.get(k), str) for k in ('message', 'source', 'level'))):
                            message, source = redact(r['message']), redact(r['source'])[:120]
                            self.rows.append({**r, 'message': message, 'source': source, 'key': self.key(r['level'], message, source)})
                elif kind == 'marker' and isinstance(data, dict) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(data.get('day', ''))):
                    self.last_day = data['day']
            except (OSError, ValueError, TypeError):
                pass
        self.prune(time.time())

    @staticmethod
    def key(level, message, source):
        return hashlib.sha256((level + '\n' + source + '\n' + message).encode('utf-8', errors='replace')).hexdigest()

    def prune(self, now):
        with self.guard:
            kept = sorted((r for r in self.rows if now - 7 * DAY <= r['last'] <= now + DAY), key=lambda r: r['last'])[-MAX_ERRORS:]
            if kept != self.rows:
                self.rows = kept
                self.dirty = True

    def add(self, level, message, source, now=None, count=1):
        now = time.time() if now is None else now
        message, source = redact(message), redact(source)[:120]
        key, hour = self.key(level, message, source), hour_start(now)
        with self.guard:
            self.prune(now)
            found = next((r for r in reversed(self.rows) if r['key'] == key and r['hour'] == hour), None)
            if found:
                found['count'] = min(10**12, found['count'] + count)
                found['last'] = now
            else:
                self.rows.append({'key': key, 'hour': hour, 'first': now, 'last': now, 'count': min(10**12, count),
                                  'level': level, 'message': message, 'source': source})
            self.prune(now)
            self.dirty = True

    def emit(self, record):
        try:
            # 审查时加：网页或 OBS 那头自己关掉连接（Windows 上是 WinError 10054 这类），不是后台出错，不记也不进日报
            if record.exc_info and isinstance(record.exc_info[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
                return
            message = re.sub(r'((?:total_)?retry_count)=\d+', r'\1=…', record.getMessage())
            if record.exc_info and record.exc_info[1]:
                message += '：' + str(record.exc_info[1])
            self.add(record.levelname, message, f'{record.name}:{record.filename}:{record.lineno}',
                     count=max(1, min(10**12, getattr(record, 'error_count', 1))))
        except Exception:
            # 错误记录自身不能再递归写日志，把原本的服务异常放大。
            pass

    def flush(self):
        with self.guard:
            try:
                if self.path and self.dirty:
                    self.writer(self.path, self.rows)
                    self.dirty = False
                if self.marker and self.marker_dirty:
                    self.writer(self.marker, {'day': self.last_day})
                    self.marker_dirty = False
            except OSError:
                return False
        return True

    def summary(self, cutoff):
        merged = {}
        with self.guard:
            rows = copy.deepcopy(self.rows)
        for row in rows:
            if cutoff - DAY <= row['hour'] < cutoff:
                group = merged.setdefault(row['key'], {**row, 'count': 0})
                group['count'] += row['count']
                group['last'] = max(group['last'], row['last'])
        if not merged:
            return ''
        lines = [f"雾幕错误汇总（截至 {dt.datetime.fromtimestamp(cutoff):%m-%d %H:%M}，过去 24 小时）",
                 f"共 {len(merged)} 种、{sum(r['count'] for r in merged.values())} 次"]
        for row in sorted(merged.values(), key=lambda r: -r['count'])[:10]:
            lines.append(f"{row['level']} ×{row['count']}，最近 {dt.datetime.fromtimestamp(row['last']):%m-%d %H:%M}：{row['message'][:95]}（{row['source'][:35]}）")
        if len(merged) > 10:
            lines.append('只列出现最多的 10 种。')
        return '\n'.join(lines).encode('utf-16-le')[:3800].decode('utf-16-le', errors='ignore')

    async def report(self, sender, now=None, demo=False):
        if demo or self.sending:
            return False
        now = time.time() if now is None else now
        current = dt.datetime.fromtimestamp(now)
        cutoff = current.replace(hour=self.hour, minute=0, second=0, microsecond=0).timestamp()
        day = current.strftime('%Y-%m-%d')
        self.flush()
        if now < cutoff or day <= self.last_day:
            return False
        text = self.summary(cutoff)
        self.sending = True
        try:
            if text:
                try:
                    if not await sender(text):
                        return False
                except Exception:
                    return False
            self.last_day, self.marker_dirty = day, True
            self.flush()
            return bool(text)
        finally:
            self.sending = False

    def install(self, loop):
        root = logging.getLogger()
        root.addHandler(self)
        old_loop, old_sys, old_thread = loop.get_exception_handler(), sys.excepthook, threading.excepthook
        def unhandled(kind, error, source):
            if not isinstance(error, (KeyboardInterrupt, SystemExit, asyncio.CancelledError,
                                      ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
                self.add('ERROR', f'{kind}：{error}', source)
                self.flush()
        def loop_error(loop, context):
            unhandled(context.get('message', '后台任务出错'), context.get('exception', ''), 'asyncio')
        def sys_error(kind, error, tb):
            unhandled(kind.__name__, error, 'sys.excepthook')
            old_sys(kind, error, tb)
        def thread_error(args):
            unhandled(args.exc_type.__name__, args.exc_value, 'threading')
            old_thread(args)
        loop.set_exception_handler(loop_error)
        sys.excepthook, threading.excepthook = sys_error, thread_error
        def restore():
            self.flush()
            root.removeHandler(self)
            loop.set_exception_handler(old_loop)
            sys.excepthook, threading.excepthook = old_sys, old_thread
        return restore

    def task_done(self, task):
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                self.add('ERROR', str(error), '后台任务:' + task.get_name())
                self.flush()
