# -*- coding: utf-8 -*-
"""雾幕：连 B 站直播间，把弹幕/进房/礼物/SC/上舰推给网页；每场结束存一份总结，能翻历史场次。

用法：python server.py --room 房间号   （或者把 room 写进 config.json，端口默认 8373）
      python server.py --room 房间号 --port 8374
      py -3 server.py --demo        （不连直播间，造假数据看样式）
      py -3 server.py --key 一串字   （不想公开时加，打开网页要用 ?key=一串字）
连接部分用的是 blivedm（blivechat 同作者，MIT 协议），放在 blivedm-src 里。
"""
import argparse
import asyncio
import collections
import datetime
import hmac
import gzip
import http.cookies
import json
import logging
import logging.handlers
import os
import random
import re
import shutil
import sys
import time
import zipfile
import urllib.parse
import uuid
import copy
from pathlib import Path

from workbench import clean_song, trusted_origin
from profiles import Profiles
from moderation import MuteService, MuteQuery
from error_journal import ErrorJournal
import connection_recovery
import input_validation as validation
import retention
from admin_links import AdminLinks, AdminSafeFormatter
from daily_health import DailyHealth
from public_limits import PublicLimits, client_ip
import history_maintenance
from ai_voice import AIVoice, Busy as VoiceBusy, VoiceError
from breaker import Breaker
from music import MusicService
import platforms
from bus import Bus
from views import (VIEWER_ROOM, VIEWER_ENTER, VIEWER_GUARD, VIEWER_USER, VIEWER_REQ, VIEWER_GUARDLIST, VIEWER_DM, VIEWER_SC,  # noqa: F401
                   VIEWER_GIFT, VIEWER_SONG, public_view, pick, viewer_gift, viewer_snapshot, viewer_view, obs_view)
import tags as tag_store
from platforms import Platforms, PLATS as PLAT_NAMES
import updates
from backend_limits import OperationError, OperationRate, WS_IMPORT_LIMIT, WS_NORMAL_LIMIT, operation_info, parse_operation

import aiohttp
from aiohttp import web

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(DIR, 'blivedm-src'))
import blivedm  # noqa: E402
import blivedm.models.web as web_models  # noqa: E402
from bili import live_ts, TrackedClient, Handler, poll_room, backfill_side_room  # noqa: E402,F401  （B 站连接这一层，2026-11-26 搬到 bili.py）

# 用来连直播间的 B 站账号登录信息（{"cookie": "..."}），不填用户名会打码。可在 config.json 的 login_file 改位置
LOGIN_FILE = os.path.join(DIR, 'data', 'bili-login.json')
DISCORD_WEBHOOK = ''  # 掉线提醒发到哪个 Discord webhook（config.json 的 discord_webhook），空着就不发
BOT_SAY_URL = ''  # 可选：让别的程序代发弹幕的本地接口（config.json 的 bot_say_url），空着就不用
# 2026-11-26 小雾版和开源版合成一份代码：主播自己的东西放进一个私有的「包」（config.json 的 pack，一个文件夹）。
# 包里 static/ 下的文件优先（自己的图、公告、manifest），static/ext/{页面}.css/.js 会自动加进那个页面（额外的 OBS 样式之类）
PACK = ''
# 软件叫什么、网页里怎么称呼主播（config.json 的 brand：{"name": "雾幕", "short": "主播"}）；主播专属链接的地址（host_path，默认 /host）
BRAND = {'name': '雾幕', 'short': '主播'}
HOST_PATH = '/host'
DISCORD_WEBHOOK_FILE = ''  # 可选：从别的程序的 JSON 配置里读 discord_webhook（config.json 的 discord_webhook_file），改了那边这里跟着变
ALERT_PORT = 0  # 只有这个端口的那份发掉线提醒（config.json 的 alert_port；同一个文件夹里另开的测试直播间不发）
MANAGED_RESTART = False  # 有别的程序（比如守护脚本）看着，退出了会自己重开（config.json 的 managed_restart，2026-11-26）
LOGIN_READONLY = False  # 登录文件是别的程序的（比如机器人的），只读不写（config.json 的 login_readonly）
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
GUARD_NAMES = {1: '总督', 2: '提督', 3: '舰长'}
BJ = datetime.timezone(datetime.timedelta(hours=8))

log = logging.getLogger('danmaku')


def load_cookie():
    try:
        with open(LOGIN_FILE, encoding='utf-8') as f:
            return json.load(f).get('cookie', '')
    except Exception:
        return ''


def make_cookies(cookie):
    cookies = http.cookies.SimpleCookie()
    for part in cookie.split(';'):
        if '=' in part:
            k, v = part.strip().split('=', 1)
            cookies[k] = v
            cookies[k]['domain'] = 'bilibili.com'
    return cookies


def uid_of(cookie):
    m = re.search(r'DedeUserID=(\d+)', cookie or '')
    return int(m.group(1)) if m else 0


# 点歌：「点歌 晴天」「想听稻香」「来一首xx」「可以唱xx吗」；提问：带问号，或者「吗 / 怎么 / 什么…」
PLAY_RE = re.compile(r'^\s*点歌\s*[:：]?\s*[《「“"]?(.{1,40}?)[》」”"]?\s*$')  # 直接放（2026-11-25）：只认「点歌 歌名」
SONG_RE = re.compile(r'(?:点歌|点一首|点首|想听|来一首|来首|求唱|唱一首|唱首|唱一下|可以唱|能唱|能不能唱)\s*[:：]?\s*[《「“"]?(.{1,30}?)[》」”"]?'
                     r'(?:吗|嘛|吧|好吗|可以吗|好不好|谢谢|[!！~～。?？\s])*$')
ASK_RE = re.compile(r'[?？]|(?:吗|呢|嘛)[~～!！。.]*$|怎么|什么|为啥|为什么|多少|哪里|哪个|几岁|几点|有没有|是不是|能不能|可以.{0,8}吗')

MONEY_KEYS = ('flow', 'income', 'total')


def clean_rules(c):
    """点歌规则：每人每场最多几首（0 = 不限），粉丝牌至少几级（0 = 不限；舰长以上不受这条限制）。"""
    def n(k, hi):
        try:
            return max(0, min(hi, int((c or {}).get(k, 0) or 0)))
        except (TypeError, ValueError, AttributeError):
            return 0
    return {'max': n('max', 50), 'medal': n('medal', 40)}


def sc_seconds(price):
    """醒目留言在 B 站置顶多久（按金额）。"""
    for p, s in ((2000, 7200), (1000, 3600), (500, 1800), (100, 300), (50, 120)):
        if price >= p:
            return s
    return 60


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_jsonl(path):
    """一行一条 JSON 的文件；坏掉的行（比如写到一半断电）跳过。"""
    out = []
    try:
        opener = gzip.open if str(path).endswith('.gz') else open
        with opener(path, 'rt', encoding='utf-8') as f:
            for line in f:
                try:
                    out.append(validation.event_row('dm', json.loads(line)))
                except (ValueError, TypeError, KeyError):
                    log.warning('跳过无效弹幕存档行')
    except OSError:
        pass
    return out


def dm_page(items, before=None, limit=200, q='', uid=0):
    """从后往前翻一页弹幕。before：只要这个序号之前的；q：搜名字或内容；uid：只看某个人。
    返回的 next 是下一页接着用的 before，more 表示前面还有没有。"""
    try:
        limit = max(1, min(int(limit or 200), 500))
    except (TypeError, ValueError):
        limit = 200
    try:
        k = len(items) if before in (None, '') else max(0, min(int(before), len(items)))
    except (TypeError, ValueError):
        k = len(items)
    q = (q or '').strip().lower()
    out = []
    while k > 0 and len(out) < limit:
        k -= 1
        d = items[k]
        if uid and d.get('uid') != uid:
            continue
        if q and q not in str(d.get('name', '')).lower() and q not in str(d.get('text', '')).lower():
            continue
        out.append(d)
    out.reverse()
    return {'items': out, 'more': k > 0, 'next': k}


class DmLog:
    """本场的全部弹幕。内存里留一份（网页往上翻、搜索、看某个人说过什么），同时一行一条追加到
    data/dmlog/房间号.jsonl，程序重启不丢。下播存历史时整份抄进那一场，新的一场开始时清空。"""

    def __init__(self, room_id, persist=True, segment=''):
        stem = f'{room_id}-{segment}' if segment else str(room_id)
        self.file = os.path.join(DIR, 'data', 'dmlog', stem + '.jsonl') if persist else None
        self.items = read_jsonl(self.file) if self.file else []
        for i, d in enumerate(self.items):
            d['i'] = i
        self.pending = []
        try:
            self.bytes = os.path.getsize(self.file) if self.file else 0
        except OSError:
            self.bytes = 0

    def add(self, item):
        item['i'] = len(self.items)  # 序号：网页拿它来接着往前翻
        self.items.append(item)
        if self.file:
            line = json.dumps(item, ensure_ascii=False)
            self.pending.append(line)
            self.bytes += len(line.encode('utf-8')) + len(os.linesep)

    def flush(self):
        if not self.pending or not self.file:
            return True
        # 失败时从内存中的完整记录原子重建，避免部分追加后重试导致重复。
        try:
            os.makedirs(os.path.dirname(self.file), exist_ok=True)
            if getattr(self, 'repair_write', False):
                tmp = self.file + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    for item in self.items:
                        f.write(json.dumps(item, ensure_ascii=False) + '\n')
                os.replace(tmp, self.file)
            else:
                with open(self.file, 'a', encoding='utf-8') as f:
                    f.write('\n'.join(self.pending) + '\n')
            self.pending.clear()
            self.repair_write = False
            return True
        except OSError as e:
            self.repair_write = True
            log.warning('弹幕存档写不进去，保留队列稍后重试：%s', e)
            return False

    def copy_to(self, path, until, count=None):
        """优先按下播时冻结的弹幕条数复制；旧的待归档记录用时间回退。"""
        rows = self.items[:count] if count is not None else [d for d in self.items if d.get('t', 0) <= until]
        if not rows:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            for d in rows:
                f.write(json.dumps({k: v for k, v in d.items() if k != 'i'}, ensure_ascii=False) + '\n')
        os.replace(tmp, path)


class Notes:
    """给观众写的备注：data/notes.json，uid -> {note, name, t}。只有管理身份看得到、改得了。"""

    def __init__(self, persist=True):
        self.file = os.path.join(DIR, 'data', 'notes.json') if persist else None
        self.data = {}
        if self.file:
            try:
                with open(self.file, encoding='utf-8') as f:
                    self.data = json.load(f)
            except (OSError, ValueError):
                pass

        self.data = validation.mapping(self.data, validation.note_row, retention.NOTES_MAX)

    def set(self, uid, name, text):
        text = str(text or '').strip()[:60]
        if text:
            if str(uid) not in self.data and len(self.data) >= retention.NOTES_MAX:
                raise ValueError('观众备注已满，请先整理已有备注')
            self.data[str(uid)] = {'note': text, 'name': str(name or '')[:64], 't': int(time.time())}
        else:
            self.data.pop(str(uid), None)
        if self.file:
            write_json(self.file, self.data)


class GuardBook:
    """记下在雾幕里看到的上舰 / 续费，估算每个人的舰长到什么时候（B 站只把准确的到期时间告诉主播本人）。
    data/guards.json，uid -> {level, until}。一个月按 30 天算，没到期又续的往后接。"""

    def __init__(self, room_id, persist=True):
        self.file = os.path.join(DIR, 'data', f'guards-{room_id}.json') if persist else None
        self.data = {}
        if self.file:
            try:
                with open(self.file, encoding='utf-8') as f:
                    self.data = json.load(f)
            except (OSError, ValueError):
                pass

        self.data = validation.mapping(self.data, validation.guard_row)

    def bought(self, uid, level, num, unit):
        days = {'年': 365, '周': 7, '天': 1}.get(unit, 30) * max(1, int(num or 1))
        now = int(time.time())
        prev = self.data.get(str(uid)) or {}
        self.data[str(uid)] = {'level': level, 'until': max(now, int(prev.get('until', 0))) + days * 86400}
        if self.file:
            write_json(self.file, self.data)

    def prune(self, now=None):
        cutoff = (time.time() if now is None else now) - retention.GUARD_EXPIRED_DAYS * retention.DAY
        expired = [uid for uid, row in self.data.items()
                   if isinstance(row, dict) and type(row.get('until')) in (int, float) and row['until'] < cutoff]
        if expired and self.file:
            expired = set(expired)
            log.info('清理已过期超过一年的上舰估算记录：%d 条', len(expired))
            kept = {uid: row for uid, row in self.data.items() if uid not in expired}
            write_json(self.file, kept)
            self.data = kept

    def until(self, uid):
        return int((self.data.get(str(uid)) or {}).get('until', 0))


class Accounts:
    """管理身份的人扫码登录自己的 B 站号（比如主播登她自己的号），用来发弹幕、禁言。
    每个浏览器各登各的：浏览器只拿到一串随机口令，登录信息（cookie）只存在电脑的 data/accounts/ 里。"""
    KEEP = ('SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5', 'sid')

    def __init__(self):
        self.dir = os.path.join(DIR, 'data', 'accounts')

    def _path(self, token):
        import hashlib
        if not token or len(token) < 20:
            return None
        return os.path.join(self.dir, hashlib.sha256(token.encode()).hexdigest()[:24] + '.json')

    def _read(self, p, uid=None):
        path = Path(p) if p else None
        if path is None or not retention.is_plain(path.parent, directory=True) or not retention.is_plain(path):
            return None
        try:
            used = path.stat().st_mtime
            now = time.time()
            if used < now - retention.ACCOUNT_IDLE_DAYS * retention.DAY:
                return None
            with path.open(encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        try:
            if not isinstance(data, dict):
                return None
            validation.text(data.get('cookie'), '登录信息', 16384, True)
            validation.integer(data.get('uid'), '账号 uid', 1)
            validation.text(data.get('uname', ''), '名字', 64)
            validation.url(data.get('face', ''))
        except ValueError:
            log.warning('跳过无效账号数据')
            return None
        if uid is None or data.get('uid') == uid:
            # 每天最多刷新一次最近使用时间；刷新失败不影响已登录的操作。
            if used < now - retention.DAY:
                try:
                    os.utime(path, (now, now))
                except OSError:
                    pass
            return data
        return None

    def get(self, token):
        return self._read(self._path(token))

    def save(self, cookie, uid, uname, face=''):
        import secrets
        folder = Path(self.dir)
        if folder.exists() and not retention.is_plain(folder, directory=True):
            raise OSError('账号数据目录不是普通目录')
        retention.prune_accounts(folder)
        if sum(1 for _ in retention.iter_plain_files(folder, retention.ACCOUNT_FILE)) >= retention.ACCOUNT_MAX:
            raise ValueError('已保存的登录过多，请先退出不再使用的账号')
        token = secrets.token_urlsafe(24)
        write_json(self._path(token), {'cookie': cookie, 'uid': uid, 'uname': uname, 'face': face, 'savedAt': int(time.time())})
        return token

    def delete(self, token):
        p = self._path(token)
        if p and os.path.exists(p):
            os.remove(p)

    def of_uid(self, uid):
        """有没有人登录过这个 UID 的号（比如主播本人），有就给它的登录信息。"""
        if not uid:
            return None
        for path in retention.iter_plain_files(Path(self.dir), retention.ACCOUNT_FILE):
            account = self._read(path, uid)
            if account:
                return account
        return None


class History:
    """每场的总结：data/history/房间号/场次.json，index.json 是给列表用的简要信息。"""
    ID_RE = re.compile(r'^\d{8}-\d{4}(?:-[0-9a-f]{12})?$')

    def __init__(self, room_id):
        self.dir = os.path.join(DIR, 'data', 'history', str(room_id))
        self.index_file = os.path.join(self.dir, 'index.json')
        self._viewers = None  # uid -> 来过的各场，用到时才从各场文件里读出来
        self._dm = (None, None)  # 最近看过的一场的整场弹幕（场次, 列表）

    def dm_file(self, sid):
        return os.path.join(self.dir, sid + '.dm.jsonl')

    def has_dm(self, sid):
        return bool(self.ID_RE.fullmatch(sid) and any(os.path.isfile(self.dm_file(sid) + suffix) for suffix in ('', '.gz')))

    def dm(self, sid):
        """某一场的整场弹幕（2026-11-12 之后的场次才有）。"""
        if not self.ID_RE.fullmatch(sid):
            return []
        cached_sid, cached_rows = self._dm
        if cached_sid == sid:
            return cached_rows
        path = self.dm_file(sid)
        rows = read_jsonl(path) if os.path.exists(path) else []
        # 整理可能刚好在打开文件前完成替换；压缩文件安装好以后才移除原文件。
        if not os.path.exists(path) and os.path.exists(path + '.gz'):
            rows = read_jsonl(path + '.gz')
        self._dm = (sid, rows)
        return rows

    def viewer(self, uid):
        """这个人以前来过哪几场：每场存历史时会带一份观众名单（viewers），老的场次只有送礼榜上的人。"""
        if self._viewers is None:
            idx = {}
            for b in self.list():
                d = self.get(b['id']) or {}
                rows = d.get('viewers') or [[u.get('uid'), u.get('name', ''), u.get('dm', 0), u.get('spend', 0), 0]
                                            for u in d.get('rank') or []]
                for r in rows:
                    idx.setdefault(r[0], []).append({'id': b['id'], 'start': b['start'], 'title': b.get('title', ''),
                                                     'dm': r[2], 'spend': r[3], 'enter': r[4]})
            self._viewers = idx
        return self._viewers.get(uid, [])

    def _index(self):
        try:
            with open(self.index_file, encoding='utf-8') as f:
                rows = validation.clean_rows(json.load(f), validation.history_row)
                return [r for r in rows if 'start' in r]
        except Exception:
            return []

    def list(self):
        return sorted(self._index(), key=lambda b: -b['start'])

    def get(self, sid):
        if not self.ID_RE.match(sid):
            return None
        try:
            with open(os.path.join(self.dir, sid + '.json'), encoding='utf-8') as f:
                return validation.history_row(json.load(f))
        except Exception:
            return None

    def save(self, summary):
        with history_maintenance.HISTORY_LOCK:
            write_json(os.path.join(self.dir, summary['id'] + '.json'), summary)
            idx = [b for b in self._index() if b['id'] != summary['id']]
            idx.append(summary['brief'])
            write_json(self.index_file, idx)
            self._viewers, self._dm = None, (None, None)

    def delete(self, sid):
        with history_maintenance.HISTORY_LOCK:
            if not self.ID_RE.match(sid):
                return False
            for p in (os.path.join(self.dir, sid + '.json'), self.dm_file(sid), self.dm_file(sid) + '.gz'):
                try:
                    os.remove(p)
                except FileNotFoundError:
                    pass
            self._viewers, self._dm = None, (None, None)
            write_json(self.index_file, [b for b in self._index() if b['id'] != sid])
            return True


class State:
    """本场数据。新的一场开播时自动清零，也可以在网页上手动清零；写到 data/房间号.json，重启不丢。"""
    KEYS = ('session_start', 'flow', 'dm', 'enters', 'gifts', 'scs', 'guards', 'users', 'gift_stats', 'stats',
            'meta', 'live_start', 'was_live', 'summarized', 'last_activity', 'reqs', 'settled_at', 'songs', 'archive_id', 'dm_segmented', 'archive_pending', 'settled_dm_count', 'outages', 'sc_read', 'live_merged')

    def __init__(self, room_id):
        self.room_id = room_id
        self.file = os.path.join(DIR, 'data', f'{room_id}.json')
        self.room = {}  # 标题、开播状态、看过人数、高能人数…
        self.bot_uids = []  # 机器人账号发的弹幕，网页上默认不朗读
        self.songs = []     # 歌单：提前写好的歌，唱完打勾；不跟着每场清零，自己管
        self.reset()
        saved = {}  # 上次存下的本场数据；没有文件就是空的
        try:
            with open(self.file, encoding='utf-8') as f:
                saved = json.load(f)
            old_keys = set(saved) if isinstance(saved, dict) else set()
            saved = validation.state_data(saved, {k: getattr(self, k) for k in self.KEYS})
            for k in self.KEYS:
                if k in saved:
                    setattr(self, k, saved[k])
        except Exception:
            pass
        previous = {k: v for k, v in saved.items() if k in old_keys} if isinstance(saved, dict) and saved else {}
        if previous and 'archive_id' not in previous:
            stamp = datetime.datetime.fromtimestamp(self.live_start or self.session_start, BJ).strftime('%Y%m%d-%H%M')
            legacy = uuid.uuid5(uuid.NAMESPACE_URL, f'xiaowu/{room_id}/{self.session_start}').hex[:12]
            self.archive_id = stamp if self.summarized else f'{stamp}-{legacy}'
            self.dm_segmented = False
        self.dirty = 'archive_id' not in previous

    def reset(self):
        self.session_start = int(time.time())
        self.archive_id = datetime.datetime.fromtimestamp(self.session_start, BJ).strftime('%Y%m%d-%H%M') + '-' + uuid.uuid4().hex[:12]
        self.dm_segmented = True
        self.archive_pending = None
        self.settled_dm_count = None
        self.live_merged = []   # 断流 5 分钟内重开时 B 站给的新开播时间，算同一场（2026-11-23）
        self.outages = []  # 本场可能漏收消息的时段，最多 200 段
        self.flow = {'gift': 0.0, 'sc': 0.0, 'guard': 0.0}  # 流水，单位元
        self.dm = []      # 最近弹幕
        self.enters = []  # 最近进房
        self.gifts = []   # 本场付费礼物
        self.scs = []
        self.sc_read = []  # 只留本场仍存在的 SC 编号，不进入历史总结。
        self.reqs = []    # 点歌 / 提问单子
        self.guards = []
        self.users = {}   # uid -> 本场来过的人
        self.gift_stats = {}  # 礼物名 -> {'num', 'yuan'}，存总结用
        self.stats = {'peak_online': 0, 'follows': 0, 'watched': 0, 'likes': 0}
        self.meta = {'title': '', 'area': ''}
        self.live_start = 0     # B 站记的这场开播时间
        self.was_live = False   # 这段时间里开过播（没开播时的数据不存历史）
        self.summarized = False
        self.settled_at = 0     # 下播存历史的时间；这之后的弹幕、进房算「下播期间」
        self.last_activity = 0
        self.dirty = True

    def touch_user(self, uid, name, face='', **inc):
        now = int(time.time())
        self.last_activity = now
        self.dirty = True
        if not uid:
            return
        key = str(uid)
        u = self.users.get(key)
        if u is None:
            u = self.users[key] = {'uid': uid, 'name': name, 'face': face, 'first': now,
                                   'last': 0, 'dm': 0, 'enter': 0, 'spend': 0.0, 'guard': 0, 'medal': ''}
        u['name'] = name or u['name']
        if face:
            u['face'] = face
        u['last'] = now
        for k, v in inc.items():
            if k in ('guard', 'medal'):
                if v:
                    u[k] = v
            else:
                u[k] = round(u.get(k, 0) + v, 2)
        if len(self.users) > 6000:
            # 人太多时，丢掉最早来过、没送过东西的
            idle = sorted((x for x in self.users.values() if not x['spend']), key=lambda x: x['last'])
            for x in idle[:1000]:
                del self.users[str(x['uid'])]

    def dm_total(self):
        return sum(u['dm'] for u in self.users.values())

    def has_activity(self):
        return self.was_live and (any(self.flow.values()) or self.dm_total() > 0)

    def summary(self, reason, end):
        start = int(max(self.live_start, self.session_start))
        total = round(sum(self.flow.values()), 2)
        rank = sorted((u for u in self.users.values() if u['spend']), key=lambda u: -u['spend'])[:100]
        gifts = sorted(({'name': k, **v} for k, v in self.gift_stats.items()), key=lambda g: -g['yuan'])
        sid = self.archive_id
        brief = {'id': sid, 'title': self.meta.get('title', ''), 'start': start, 'end': int(end),
                 'total': total, 'income': round(total / 2, 2), 'flow': self.flow,
                 'dm_total': self.dm_total(), 'user_count': len(self.users),
                 'sc_count': len(self.scs), 'guard_count': len(self.guards),
                 'peak_online': self.stats.get('peak_online', 0), 'reason': reason}
        return {**brief, 'brief': brief, 'room_id': self.room_id, 'area': self.meta.get('area', ''),
                'stats': self.stats, 'outages': copy.deepcopy(self.outages),
                'rank': [{k: u[k] for k in ('uid', 'name', 'face', 'spend', 'guard', 'dm')} for u in rank],
                'scs': self.scs, 'guards': self.guards, 'gift_stats': gifts, 'broadcast_start': self.live_start,
                'big_gifts': [g for g in self.gifts if g['yuan'] >= 50],
                # 这场来过的人（观众档案用）：[uid, 名字, 弹幕数, 送出, 进房次数]
                'viewers': [[u['uid'], u['name'], u.get('dm', 0), round(u.get('spend', 0), 2), u.get('enter', 0)]
                            for u in self.users.values() if u.get('dm') or u.get('spend') or u.get('enter')]}

    def prune_sc_read(self):
        kept = validation.clean_sc_read(self.sc_read, self.scs)
        if kept != self.sc_read:
            self.sc_read = kept
            self.dirty = True

    def snapshot(self):
        self.prune_sc_read()
        recent = sorted(self.users.values(), key=lambda u: -u['last'])[:500]
        ids = {u['uid'] for u in recent}
        # 送过东西的人全带上，送礼榜才完整
        spenders = [u for u in self.users.values() if u['spend'] and u['uid'] not in ids]
        return {'room_id': self.room_id, 'room': self.room, 'session_start': self.session_start,
                'live_from': self.live_start if self.live_merged else 0,  # 断流重开合并过：已播时长从第一次开播算
                'archive_id': self.archive_id, 'outages': self.outages, 'flow': self.flow, 'dm': self.dm[-200:], 'enters': self.enters[-100:],
                'gifts': self.gifts[-300:], 'scs': self.scs, 'sc_read': list(self.sc_read), 'guards': self.guards,
                'users': recent + spenders, 'user_count': len(self.users), 'bot_uids': self.bot_uids,
                'dm_total': self.dm_total(), 'reqs': self.reqs, 'songs': self.songs}

    def save(self):
        self.prune_sc_read()
        if not self.dirty or not self.file:
            return
        data = {k: getattr(self, k) for k in self.KEYS}
        data['dm'] = self.dm[-200:]
        data['enters'] = self.enters[-100:]
        try:
            write_json(self.file, data)
        except OSError as e:
            log.warning('本场保存失败，将重试：%s', e)
            return False
        self.dirty = False
        return True


class Hub:
    def __init__(self, state, history, persist=True):
        self.state = state
        self.history = history
        self.dmlog = DmLog(state.room_id, persist, state.archive_id if state.dm_segmented else '')      # 本场全部弹幕
        self.notes = Notes(persist)                      # 观众备注
        self.guardbook = GuardBook(state.room_id, persist)  # 看到过的上舰 / 续费，估到期时间用
        self.guardlist = []                              # 现有的舰长名单（poll_guards 定时更新）
        self.recover_wake = asyncio.Event()
        self.guard_recovery = False
        self.restart_count, self.restart_after = 0, 0
        self.stopping = False
        self.guard_wake = asyncio.Event()                # 有人上舰了：马上重新查一次名单
        self.songbook_file = os.path.join(DIR, 'data', 'songbook.json') if persist else None
        self.songbook = {}
        if self.songbook_file:
            try:
                with open(self.songbook_file, encoding='utf-8') as f:
                    self.songbook = json.load(f)
            except (OSError, ValueError):
                pass
        self.songbook = validation.mapping(self.songbook, validation.library_row, SONGBOOK_MAX)
        for song in state.songs:
            if not song.get('done'):
                self.link_requests(song)
        # 补标「下播」（2026-11-18）：这场已经下播存过历史，之后送的礼物 / 开的舰长都是下播期间的。
        # 以前重启后还没问到开播状态时送的会漏标，这里按时间补上
        if state.summarized and state.settled_at:
            for x in state.gifts + state.guards:
                if not x.get('source') and x.get('t', 0) > state.settled_at:
                    x['source'] = '下播'
        # 2026-11-25：以前每开一场都把所有下播礼物带过来，感谢过的也一直挂着。上一段下播带过来、已经感谢过的清掉
        # （它们在 data/offline 的下播记录里都有，「下播期间」页照样看得到）
        start = state.session_start or 0
        for key in ('gifts', 'guards'):
            items = getattr(state, key)
            keep = [x for x in items if not (x.get('source') == '下播' and x.get('thanked') and x.get('t', 0) < start)]
            if len(keep) != len(items):
                setattr(state, key, keep)
                state.dirty = True
        self.rules_file = os.path.join(DIR, 'data', 'req-rules.json') if persist else None
        # 常用标题 + 分区（2026-11-18）：开播前点一下换好，存在电脑上，各设备一样
        self.tpre_file = os.path.join(DIR, 'data', 'title-presets.json') if persist else None
        self.title_presets = []
        if self.tpre_file:
            try:
                with open(self.tpre_file, encoding='utf-8') as f:
                    self.title_presets = validation.title_presets(json.load(f))
            except (OSError, ValueError):
                self.title_presets = []
        # B 站 SC 各档（500 / 1000 / 2000）的装饰图，见过就记下（2026-11-21）
        self.sc_icons_file = os.path.join(DIR, 'data', 'sc-icons.json') if persist else None
        self.sc_icons = {}
        if self.sc_icons_file and os.path.exists(self.sc_icons_file):
            try:
                with open(self.sc_icons_file, encoding='utf-8') as f:
                    raw = json.load(f)
                self.sc_icons = {k: validation.safe_url(v) for k, v in raw.items() if k in ('500', '1000', '2000') and isinstance(v, str)} if isinstance(raw, dict) else {}
            except (OSError, ValueError):
                self.sc_icons = {}
        # 事件总线（2026-11-26）：每条消息记下来以后发一次，点歌、查头像这些顺便做的事都订阅它
        self.bus = Bus()
        self.bus.on('dm', self.on_dm_request)
        self.bus.on('*', self.on_face)
        # 身份标签（2026-11-26）：自带标签改名字 / 颜色、自己的标签、手动标的机器人
        self.tags = tag_store.Tags(os.path.join(DIR, 'data', 'tags.json') if persist else None, write_json)
        state.manual_bots = list(self.tags.bots)
        set_bots(state)
        # 普通链接能切到哪些直播间（2026-11-21）：管理链接里增删、随时开关，最多 XROOMS_MAX 个
        self.xrooms_file = os.path.join(DIR, 'data', 'xrooms.json') if persist else None
        self.xrooms = {'open': True, 'rooms': []}
        if self.xrooms_file and os.path.exists(self.xrooms_file):
            try:
                with open(self.xrooms_file, encoding='utf-8') as f:
                    self.xrooms = validation.xrooms(json.load(f))
            except (OSError, ValueError):
                pass
        # 设置方案（配色、布局、朗读…）存在电脑上，换设备也能用（Codex 第 2 轮，2026-11-13 合并）
        self.profiles = Profiles(os.path.join(DIR, 'data', 'profiles.json') if persist else None, write_json)
        self.req_rules = clean_rules({})
        if self.rules_file:
            try:
                with open(self.rules_file, encoding='utf-8') as f:
                    self.req_rules = clean_rules(json.load(f))
            except (OSError, ValueError):
                pass
        self.emots_file = os.path.join(DIR, 'data', 'emots.json') if persist else None
        self.emots = {}                                  # 小表情：'[妙]' -> 图片地址
        if self.emots_file:
            try:
                with open(self.emots_file, encoding='utf-8') as f:
                    self.emots = json.load(f)
            except (OSError, ValueError):
                pass
        emots = retention.trim_emots(self.emots) if isinstance(self.emots, dict) else {}
        if emots != self.emots:
            if self.emots_file:
                try:
                    write_json(self.emots_file, emots)
                except OSError as e:
                    log.warning('小表情缓存暂未清理：%s', e)
            self.emots = emots
        self.rotate_after = 0
        if self.dmlog.items:
            state.dm = self.dmlog.items[-300:]
        else:
            # 第一次用上弹幕存档时，把已经记着的最近弹幕先放进去
            old, state.dm = state.dm, []
            for d in old:
                self.dmlog.add(d)
            state.dm = self.dmlog.items[-300:]
        self.obs_clients = {}
        self.obs_opts = {}  # OBS 页面网址里的设置：{'price': 显示价格, 'gm': 礼物最低价}（2026-11-21）
        self.sockets = {}  # ws -> 是不是管理身份（只有管理身份收得到收益数字）
        self.admin_links = None
        self.link_sockets = {}
        self.public_limits = None
        self.viewers = set()  # 普通链接的连接（不是管理、也不是 OBS 页面）：只发 viewer_view 挑出来的那一点
        self.wake = asyncio.Event()  # 收到开播消息时叫醒 poll_room 马上查一次
        self.bili_message_seen = False
        self.bili_seen = time.time()  # 最后一次收到 B 站消息的时间（心跳每 30 秒一次）；刚启动先算连着
        if state.outages and state.outages[-1].get('up_at') is None:
            self.bili_seen = state.outages[-1]['down_at']

    def socket_allowed(self, ws):
        link = self.link_sockets.get(ws)
        return ws in self.sockets and (not link or self.admin_links.active(link))

    def drop_socket(self, ws):
        self.sockets.pop(ws, None)
        self.viewers.discard(ws)
        self.obs_clients.pop(ws, None)
        self.obs_opts.pop(ws, None)
        self.link_sockets.pop(ws, None)
        if self.public_limits:
            self.public_limits.release(ws)

    def invalidate_links(self):
        closed = [ws for ws, link in self.link_sockets.items() if not self.admin_links.active(link)]
        # 先同步撤掉所有推送与操作权限，再等待网络关闭，慢客户端不能拖延作废。
        for ws in closed:
            self.drop_socket(ws)
        return closed

    async def close_links(self, sockets):
        async def close(ws):
            try:
                await asyncio.wait_for(ws.close(code=4001, message='管理链接已失效，请重新打开链接'.encode()), 2)
            except (asyncio.TimeoutError, ConnectionError):
                pass
        await asyncio.gather(*(close(ws) for ws in sockets))

    async def push(self, kind, data, **extra):
        full = json.dumps({'type': kind, 'data': data, **extra}, ensure_ascii=False)
        pub = json.dumps({'type': kind, 'data': public_view(data), **extra}, ensure_ascii=False)

        slim = None
        if self.viewers:
            view = viewer_view(kind, data)
            slim = False if view is None else json.dumps({'type': kind, 'data': view, **extra}, ensure_ascii=False)

        obs_bodies = {}

        def obs_body(gm):
            if gm not in obs_bodies:
                obs_bodies[gm] = json.dumps({'type': kind, 'data': obs_view(kind, public_view(data), gm), **extra}, ensure_ascii=False)
            return obs_bodies[gm]

        async def send(ws, admin):
            if not self.socket_allowed(ws):
                return
            body = full if admin else pub
            o = self.obs_opts.get(ws)
            if o and not o['price'] and kind in ('gift', 'guard', 'guards_all', 'snapshot'):
                body = obs_body(o['gm'])
            if not admin and ws in self.viewers:
                if not slim:
                    return  # 这类消息不给普通链接
                body = slim
            try:
                await asyncio.wait_for(ws.send_str(body), 10)
            except Exception:
                self.drop_socket(ws)
                await ws.close()
        # 一起发，网速慢的人不拖累别人
        await asyncio.gather(*(send(ws, a) for ws, a in list(self.sockets.items())))

    def need_face(self, uid):
        """没头像的人（2026-11-25）：排队去 B 站名片接口查一下（不带登录），查到了推 face 给网页补上"""
        q = getattr(self, 'face_q', None)
        if q is None or not isinstance(uid, int) or uid <= 0 or uid in self.face_seen:
            return
        if (self.state.users.get(str(uid)) or {}).get('face'):
            return
        if len(self.face_seen) > 5000:
            self.face_seen.clear()
        self.face_seen.add(uid)
        if q.qsize() < 200:
            q.put_nowait(uid)

    def got_face(self, uid, face):
        s = self.state
        u = s.users.get(str(uid))
        if u is not None and not u.get('face'):
            u['face'] = face
            s.dirty = True
        for g in s.guards[-200:]:
            if g.get('uid') == uid and not g.get('face'):
                g['face'] = face
                s.dirty = True
        self.emit('face', {'uid': uid, 'face': face})

    def emit(self, kind, data, **extra):
        asyncio.get_event_loop().create_task(self.push(kind, data, **extra))

    def songs_view(self, songs=None):
        """发给网页的歌单：带上曲库里填的歌手和标签（网页按它分组）。只在发出去时加，存盘的歌单不变。"""
        out = []
        for x in self.state.songs if songs is None else songs:
            b = self.songbook.get(x['name']) or {}
            row = dict(x)
            if b.get('artist'):
                row['artist'] = b['artist']
            if b.get('tags'):
                row['tags'] = b['tags']
            out.append(row)
        return out

    def link_requests(self, song):
        current = {r['id'] for r in self.state.reqs}
        ids = song.setdefault('req_ids', [])
        ids[:] = [rid for rid in ids if rid in current]
        for request in self.state.reqs:
            if not request['done'] and not request.get('over') and request.get('song', '').casefold() == song['name'].casefold():
                if request['id'] not in ids:
                    ids.append(request['id'])
                    self.state.dirty = True
                if request.get('queued_id') != song['id']:
                    request['queued_id'] = song['id']
                    self.state.dirty = True

    def save_songbook(self):
        if self.songbook_file:
            write_json(self.songbook_file, self.songbook)
        self.emit_admin('songbook', self.songbook_list())
        self.emit_admin('library', self.library_list())

    def songbook_add(self, name, sung=False, performance=''):
        name = str(name or '').strip()[:80]
        if not name:
            return
        old = copy.deepcopy(self.songbook)
        if name not in self.songbook and len(self.songbook) >= SONGBOOK_MAX:
            # 只让无资料、也不在歌单中的记录腾位置。全是主播整理过的歌时照常排歌，不扩张曲库。
            queued = {song['name'] for song in self.state.songs}
            spare = [
                k for k, v in self.songbook.items()
                if k not in queued and not any(v.get(f) for f in ('artist', 'tags', 'backing', 'note', 'key', 'lyrics'))
                and v.get('level', '待整理') == '待整理' and v.get('available') is not False
            ]
            if not spare:
                return
            victim = min(spare, key=lambda k: (self.songbook[k].get('last', 0), self.songbook[k].get('n', 0)))
            log.info('曲库已满，移除一首无资料且不在歌单中的歌曲')
            del self.songbook[victim]
        b = self.songbook.setdefault(name, {'n': 0, 'last': 0})
        played = b.setdefault('played', [])
        if sung and (not performance or performance not in played):
            b['n'] = b.get('n', 0) + 1
            b['last'] = int(time.time())
            if performance:
                played.append(performance)
        # 仍可撤销的歌单演唱不能丢编号，另外留最近 50 次历史记录。
        active = {song['id'] for song in self.state.songs if song['name'] == name}
        keep = active.union(played[-50:])
        played[:] = [item for item in played if item in keep]
        try:
            self.save_songbook()
        except OSError:
            self.songbook = old
            raise

    def songbook_list(self):
        return [[k, v.get('n', 0), v.get('last', 0)] for k, v in self.songbook.items()]

    def library_list(self):
        return [{**clean_song({'name': k, **{f: v[f] for f in ('artist', 'tags', 'level', 'key', 'backing', 'available', 'note', 'lyrics') if f in v}}),
                 'n': v.get('n', 0), 'last': v.get('last', 0)} for k, v in self.songbook.items()]

    def library_cmd(self, cmd, c):
        old = copy.deepcopy(self.songbook)
        try:
            if cmd == 'library_delete':
                name = str(c.get('name', ''))
                if any(x['name'] == name and not x['done'] for x in self.state.songs):
                    raise ValueError('这首歌还在待唱歌单中，请先从歌单移除')
                self.songbook.pop(name, None)
                result = '已从曲库删除；历史场次不受影响'
            else:
                rows = c.get('rows') if cmd == 'library_import' else [c.get('song')]
                if not isinstance(rows, list) or not 0 < len(rows) <= 3000:
                    raise ValueError('一次请导入 1–3000 首歌')
                cleaned = [clean_song(row) for row in rows]
                for row in cleaned:
                    name = row.pop('name')
                    if len(self.songbook) >= SONGBOOK_MAX and name not in self.songbook:
                        raise ValueError('曲库已达到 10000 首上限，请先整理')
                    b = self.songbook.setdefault(name, {'n': 0, 'last': 0})
                    b.update(row)  # 唱过次数由歌单完成事件维护，不信任导入文件里的计数
                result = f'已保存 {len(cleaned)} 首歌曲资料'
            self.save_songbook()
            self.emit('songs', self.songs_view())
        except (OSError, ValueError):
            self.songbook = old
            raise
        return result


    def learn_emots(self, emots):
        """记下见过的小表情图片地址（data/emots.json）：以前存下的弹幕、历史场次里的 [妙] 也能显示成图。"""
        new = {k: v for k, v in retention.trim_emots(emots).items() if self.emots.get(k) != v}
        if not new:
            return
        combined = {k: v for k, v in self.emots.items() if k not in new}
        combined.update(new)
        combined = retention.trim_emots(combined)
        if self.emots_file:
            write_json(self.emots_file, combined)
        self.emots = combined
        self.emit('emots', {k: v for k, v in new.items() if k in combined})

    def emit_admin(self, kind, data):
        """只发给管理身份的网页（比如观众备注）。"""
        msg = json.dumps({'type': kind, 'data': data}, ensure_ascii=False)

        async def send(ws):
            if not self.socket_allowed(ws):
                return
            try:
                await asyncio.wait_for(ws.send_str(msg), 10)
            except Exception:
                self.drop_socket(ws)
                await ws.close()
        for ws, admin in list(self.sockets.items()):
            if admin:
                asyncio.get_event_loop().create_task(send(ws))

    def user(self, uid):
        return self.state.users.get(str(uid))

    # ---- 场次 ----
    def settle(self, reason, end=None, retry=False):
        s = self.state
        summary = s.archive_pending
        if summary is None:
            if not s.has_activity() and not (s.was_live and self.dmlog.items):
                return
            summary = s.summary(reason, end or time.time())
            # 明确给了截止时间表示补结算，不能算入截止之后的旧弹幕。
            if end is None:
                summary['dm_log_count'] = len(self.dmlog.items)
            else:
                summary['dm_log_count'] = next(
                    (i for i, row in enumerate(self.dmlog.items) if row.get('t', 0) > summary['end']),
                    len(self.dmlog.items),
                )
            if retry:
                # 固定下播时的统计和弹幕截止时间，避免把下播后的互动算进去。
                summary = s.archive_pending = copy.deepcopy(summary)
                s.dirty = True
        dm_count = summary.get('dm_log_count')
        self.dmlog.copy_to(self.history.dm_file(summary['id']), summary['end'], dm_count)
        self.history.save(summary)
        s.settled_dm_count = dm_count
        s.archive_pending = None
        s.summarized = True
        s.settled_at = summary['end']
        s.dirty = True
        log.info('这场已存进历史：%s 流水 %.2f 元', summary['id'], summary['total'])
        self.emit('history', summary['brief'])

    def close_broadcast(self, reason, end=None):
        if self.state.summarized:
            return
        try:
            self.settle(reason, end, retry=True)
        except OSError as e:
            log.warning('下播存档将在下次重试：%s', e)

    def can_resume(self, start):
        """断流后又开播（B 站给了新的开播时间）：离下播不到 5 分钟就算同一场（2026-11-23 用户要求）。
        下播时照常先存一份历史防丢；接回来以后，最后下播再用同一个场次编号覆盖那份存档。"""
        s = self.state
        if not (s.was_live and s.live_start and start > s.live_start):
            return False
        if s.archive_pending:
            ref = s.archive_pending.get('end', 0)
        elif s.summarized:
            ref = s.settled_at
        else:
            # 断得太短，PREPARING 和每分钟的查询都没看到下播：按上次查到「在播」的时间算（只在程序一直开着时有）
            ref = getattr(self, 'live_seen_at', 0)
        return bool(ref) and start - ref < SAME_SESSION_SEC

    def resume_session(self, start):
        s = self.state
        gap_from = s.settled_at or (s.archive_pending or {}).get('end', 0)
        s.archive_pending = None
        s.summarized = False
        s.settled_at = 0
        s.settled_dm_count = None
        if gap_from:
            # 断流那几分钟送的礼物、上舰本来标着「下播」，现在算回这一场
            for key in ('gifts', 'guards'):
                for x in getattr(s, key):
                    if x.get('source') == '下播' and x.get('t', 0) >= gap_from - 5:
                        x.pop('source', None)
        s.live_merged = (list(s.live_merged or []) + [start])[-20:]
        s.dirty = True
        log.info('断流后又开播（隔了约 %d 秒），算同一场，接着统计：%s', max(0, start - (gap_from or start)), s.archive_id)
        snap = s.snapshot()
        snap['songs'] = self.songs_view()
        self.emit('snapshot', snap)

    def save_offline(self):
        s = self.state
        since = s.settled_at if s.summarized else 0
        keep = {k: [x for x in getattr(s, k) if x.get('t', 0) > since]
                for k in ('enters', 'gifts', 'scs', 'guards', 'reqs')}
        if s.summarized and s.settled_dm_count is not None:
            keep['dm'] = self.dmlog.items[s.settled_dm_count:]
        else:
            keep['dm'] = [x for x in self.dmlog.items if x.get('t', 0) > since]
        if not any(keep.values()):
            return
        d = os.path.join(DIR, 'data', 'offline', str(s.room_id))
        write_json(os.path.join(d, s.archive_id + '.json'), {'from': since, 'to': int(time.time()), **keep})

    def new_session(self, reason):
        s = self.state
        log_file = self.dmlog.file
        continuing_live = s.room.get('live') == 1 or (s.was_live and not s.summarized and not s.archive_pending)
        if s.archive_pending:
            self.settle(reason)
        if s.summarized or not s.was_live:
            self.save_offline()
        else:
            # 程序关着时换了一场（自动结算）：上一场按最后一条互动的时间收尾，不然时长会一直算到这一场开播（2026-11-13 Claude 审查补回）
            self.settle(reason, s.last_activity or None if reason == '自动结算' else None)
        # 旧分段留给维护任务逐条核对；在切换前确保它也有完整副本。
        if not self.dmlog.flush():
            raise OSError('旧分段弹幕未写入磁盘')
        old = {key: getattr(s, key) for key in s.KEYS}
        s.reset()
        if reason == '自动结算':
            # 下播期间送的礼物、开的舰长留到这一场，标着「下播」（2026-11-18 用户要求；钱不算进这一场的流水）
            # 2026-11-25 用户：已经点了「感谢」的就不带过来了（下播期间页里照样查得到），以前会一场一场一直带着
            s.gifts = [x for x in old['gifts'] if x.get('source') == '下播' and not x.get('thanked')][-300:]
            s.guards = [x for x in old['guards'] if x.get('source') == '下播' and not x.get('thanked')][-100:]
        if reason in ('手动清零', '容量分段') and continuing_live:
            s.was_live = True
            s.live_start = old['live_start']
            s.meta = old['meta']
            if old['outages'] and old['outages'][-1].get('up_at') is None:
                s.outages = [{'down_at': s.session_start, 'up_at': None}]
        # 先提交当前状态，重启时按场次编号选择日志。
        if s.save() is False:
            for key, value in old.items():
                setattr(s, key, value)
            s.dirty = True
            raise OSError('无法保存新的场次')
        self.dmlog = DmLog(s.room_id, log_file is not None, s.archive_id)
        snap = s.snapshot()
        snap['songs'] = self.songs_view()
        self.emit('snapshot', snap)

    def rotate_large_segment(self):
        s = self.state
        now = time.monotonic()
        if now < self.rotate_after or s.archive_pending:
            return
        # 重启后先等真实房间状态，避免旧场次在开播时间尚未核对时提前切开。
        if s.was_live and not s.summarized and s.room.get('live') is None:
            return
        if (len(self.dmlog.items) < retention.SEGMENT_DM_ROWS
                and self.dmlog.bytes < retention.SEGMENT_DM_BYTES
                and len(s.users) < retention.SEGMENT_USERS
                and len(s.scs) < retention.SEGMENT_SC
                and len(s.guards) < retention.SEGMENT_GUARDS
                and len(s.gift_stats) < retention.SEGMENT_GIFT_TYPES
                and all(len(r.get('fans') or []) < retention.SEGMENT_FANS for r in s.reqs)):
            return
        try:
            self.new_session('容量分段')
        except OSError as e:
            self.rotate_after = now + 60
            log.warning('容量分段失败，保留原数据后重试：%s', e)


    def valid_event(self, kind, values):
        try:
            validation.event(kind, values)
            return True
        except ValueError as e:
            log.warning('跳过无效直播条目 %s：%s', kind, e)
            return False

    # ---- 下面几个是收到消息后统一的处理，真实直播间和演示模式都走这里 ----
    def danmaku(self, uid, name, face, text, medal='', medal_level=0, guard=0, admin=False, emoticon='', medal_room=0, emots=None, medal_lit=1,
                wealth=0, reply='', dmid='', plat=''):
        face, emoticon = validation.safe_url(face), validation.safe_url(emoticon)  # 图片地址不对只去掉图，弹幕照收
        if not self.valid_event('dm', {'uid': uid, 'name': name, 'face': face, 'text': text, 'medal': medal, 'medal_level': medal_level,
                                       'guard': guard, 'admin': admin, 'emoticon': emoticon, 'medal_room': medal_room, 'emots': emots}):
            return
        item = {'t': int(time.time()), 'uid': uid, 'name': name, 'face': face, 'text': text,
                'medal': medal, 'medal_level': medal_level, 'medal_room': medal_room,  # 粉丝牌是哪个直播间的
                'guard': guard, 'admin': admin, 'emoticon': emoticon}
        if medal and not medal_lit:
            item['medal_dim'] = 1  # 粉丝牌是灰的（没点亮），网页上也显示成灰的（2026-11-18）
        # 2026-11-19 跟 B 站一样：荣耀等级（财富等级）、回复了谁（@）
        if isinstance(wealth, int) and 0 < wealth < 1000:
            item['wealth'] = wealth
        if isinstance(reply, str) and reply.strip():
            item['reply'] = reply.strip()[:40]
        if isinstance(dmid, str) and re.fullmatch(r'[0-9a-zA-Z]{1,64}', dmid):
            item['dmid'] = dmid
        if plat in PLAT_NAMES:
            item['plat'] = plat  # 其他平台的弹幕（2026-11-25）：网页上标「斗鱼」「虎牙」「抖音」  # B 站这条弹幕的编号（2026-11-21：回复某条弹幕用）
        if emots:
            item['emots'] = retention.trim_emots(emots)
            self.learn_emots(item['emots'])
        s = self.state
        self.dmlog.add(item)
        s.dm.append(item)
        del s.dm[:-300]
        s.touch_user(uid, name, face, dm=1, guard=guard, medal=(f'{medal} {medal_level}' + ('' if medal_lit else ' dim')) if medal else '')
        self.bus.publish('dm', item)
        self.emit('dm', item, uc=len(s.users))

    def on_dm_request(self, item):
        """订阅：弹幕里的点歌（直接放 / 进点歌列表）。主播自己、机器人、表情包不算"""
        s = self.state
        if not item.get('emoticon') and item['uid'] not in s.bot_uids and item['uid'] != s.room.get('uid'):
            if not self.music_dm(item):
                self.collect(item)

    def on_face(self, kind, item):
        """订阅：没头像的人去 B 站名片查（礼物 / SC / 上舰的头像在 item 里）"""
        if not item.get('face'):
            self.need_face(item.get('uid'))

    block_logged = False

    def room_notice(self, text, link=''):
        """B 站在直播间里发的活动 / 系统横幅（COMMON_NOTICE_DANMAKU，比如「逃离鸭科夫：雾冬Hanaki 未能抵御第 1 级风暴…」，2026-11-23 用户要）：
        当成一条特殊弹幕（kind = notice）放进弹幕列表和存档，不算发言、不朗读、不上 OBS。"""
        text = re.sub(r'\s+', ' ', str(text or '')).strip()[:200]
        if not text:
            return
        s = self.state
        if any(d.get('kind') == 'notice' and d.get('text') == text and time.time() - d.get('t', 0) < 60 for d in s.dm[-30:]):
            return  # 同一条横幅一分钟里推了好几次，只记一次
        item = {'t': int(time.time()), 'uid': 0, 'name': '', 'face': '', 'text': text, 'kind': 'notice',
                'medal': '', 'medal_level': 0, 'medal_room': 0, 'guard': 0, 'admin': False, 'emoticon': ''}
        link = validation.safe_url(link) if link else ''
        if link:
            item['link'] = link
        self.dmlog.add(item)
        s.dm.append(item)
        del s.dm[:-300]
        self.emit('dm', item, uc=len(s.users))

    def room_block(self, uid, name, raw):
        """禁言提示：当成一条特殊弹幕（kind = mute）放进弹幕列表和存档，不算发言、不读、不收点歌。"""
        if not Hub.block_logged:  # 第一次记下 B 站给的原始字段，方便以后补「有效期」这类信息
            Hub.block_logged = True
            log.info('收到禁言提示，字段：%s', sorted(raw.keys()) if isinstance(raw, dict) else type(raw).__name__)
        who = {1: '房管', 2: '主播'}.get(raw.get('operator') if isinstance(raw, dict) else None, '')
        text = f'已被{who}禁言' if who else '已被禁言'
        if not self.valid_event('dm', {'uid': uid, 'name': name, 'text': text}):
            return
        item = {'t': int(time.time()), 'uid': uid, 'name': name, 'face': '', 'text': text, 'kind': 'mute',
                'medal': '', 'medal_level': 0, 'medal_room': 0, 'guard': 0, 'admin': False, 'emoticon': ''}
        s = self.state
        self.dmlog.add(item)
        s.dm.append(item)
        del s.dm[:-300]
        self.emit('dm', item, uc=len(s.users))

    def music_dm(self, d):
        """弹幕点歌直接放（2026-11-25）：开着的话「点歌 歌名」进放歌队列、「切歌」按规则切；别的弹幕照旧"""
        m = getattr(self, 'music', None)
        if not m or not m.rules['on']:
            return False
        text = d['text'].strip()
        if text == '切歌':
            m.skip_by(d)
            return True
        hit = PLAY_RE.match(text)
        if not hit or hit.group(1).strip() in ('什么', '啥', '歌', '一首', '首歌', '一首歌'):
            return False
        s = self.state
        followed = any(e.get('uid') == d['uid'] and e.get('kind') == 'follow' for e in s.enters[-200:])
        own = s.room.get('room_real') or s.room_id
        asyncio.get_event_loop().create_task(m.request(d, hit.group(1).strip(), own, followed))
        return True

    def collect(self, d):
        """点歌 / 提问收集：认出来的弹幕记进单子，网页上「点歌 & 提问」面板显示。"""
        s, text = self.state, d['text'].strip()
        m = SONG_RE.search(text)
        song = m.group(1).strip(' 　《》「」“”"') if m else ''
        if song and song not in ('什么', '啥', '歌', '一首', '首歌', '一首歌'):
            kind = 'song'
        else:
            return  # 提问收集用户不要了（2026-11-12），只收点歌
        if any(r['uid'] == d['uid'] and r['text'] == text for r in s.reqs[-50:]):
            return
        # 点歌规则：不合规则的照样记下，标上原因，网页上变灰，主播还是可以手动加进歌单
        rules, over = self.req_rules, ''
        own = s.room.get('room_real') or s.room_id
        if rules['medal'] and not d.get('guard') and not (
                (d.get('medal_level') or 0) >= rules['medal'] and (not d.get('medal_room') or d.get('medal_room') == own)):
            over = f"粉丝牌不到 {rules['medal']} 级"
        if kind == 'song' and not over:
            # 同一首歌还没唱的话，多个人点就合成一条，记下都有谁点了
            same = next((r for r in s.reqs if r['kind'] == 'song' and not r['done'] and not r.get('over') and r['song'].lower() == song.lower()), None)
            if same:
                fans = same.setdefault('fans', [])
                if d['uid'] != same['uid'] and all(f['uid'] != d['uid'] for f in fans):
                    fans.append({'uid': d['uid'], 'name': d['name']})
                    s.dirty = True
                    self.emit('reqs', s.reqs)
                return
        if not over and rules['max'] and sum(1 for r in s.reqs if r['uid'] == d['uid'] and r['kind'] == 'song' and not r.get('over')) >= rules['max']:
            over = f"每人最多 {rules['max']} 首"
        s.req_seq = uuid.uuid4().hex[:12]
        item = {'id': f"{d['t']}-{s.req_seq}", 't': d['t'], 'uid': d['uid'], 'name': d['name'], 'face': d['face'],
                'guard': d['guard'], 'kind': kind, 'text': text, 'song': song, 'done': False}
        if over:
            item['over'] = over
        queued = None if over else next((x for x in s.songs if not x['done'] and x['name'].casefold() == song.casefold()), None)
        if queued:
            queued.setdefault('req_ids', []).append(item['id'])
            item['queued_id'] = queued['id']
        s.reqs.append(item)
        if len(s.reqs) > 300:
            removed = s.reqs.pop(0)
            for song in s.songs:
                ids = song.get('req_ids') or []
                if removed['id'] in ids:
                    ids.remove(removed['id'])
        s.dirty = True
        self.emit('req', item)

    def obs_test(self):
        """开播前测试：只发给打开着的 OBS 弹幕页，一条弹幕、一条 SC、一条上舰，隔一秒多一条；不进本场数据。"""
        targets = [ws for ws, kind in self.obs_clients.items() if kind == 'obs']
        t = int(time.time())
        msgs = [('dm', {'t': t, 'uid': 1, 'name': '测试·' + BRAND['name'], 'face': '', 'text': '这是一条测试弹幕，看得到就好～', 'medal': '', 'medal_level': 0,
                        'medal_room': 0, 'guard': 0, 'admin': False, 'emoticon': '', 'i': -1}),
                ('sc', {'item': {'id': f'test{t}', 't': t, 'uid': 1, 'name': '测试·' + BRAND['name'], 'face': '', 'price': 30, 'text': '测试 SC：位置和颜色都对吗', 'guard': 0}}),
                ('guard', {'item': {'t': t, 'uid': 1, 'name': '测试·' + BRAND['name'], 'level': 3, 'level_name': '舰长', 'num': 1, 'unit': '月', 'yuan': 0}})]

        async def run():
            for i, (kind, data) in enumerate(msgs):
                if i:
                    await asyncio.sleep(1.5)
                body = json.dumps({'type': kind, 'data': data}, ensure_ascii=False)
                for ws in targets:
                    try:
                        await ws.send_str(body)
                    except Exception:
                        pass
        if targets:
            asyncio.get_event_loop().create_task(run())
        return len(targets)

    def set_req_rules(self, c):
        rules = clean_rules(c)
        if self.rules_file:
            write_json(self.rules_file, rules)
        self.req_rules = rules
        self.emit('req_rules', rules)
        return '点歌规则已保存'

    def req_cmd(self, cmd, rid='', kind=''):
        s = self.state
        if cmd == 'req_done':
            for r in s.reqs:
                if r['id'] == rid:
                    linked_song = next((x for x in s.songs if x['id'] == r.get('queued_id')), None)
                    if linked_song:
                        self.song_cmd('song_done', linked_song['id'], options={'done': not r['done']})
                    else:
                        r['done'] = not r['done']
        elif cmd == 'req_del':
            s.reqs = [r for r in s.reqs if r['id'] != rid]
        elif cmd == 'req_clear':  # 清掉某一类里已经勾掉的
            s.reqs = [r for r in s.reqs if not (r['kind'] == kind and r['done'])]
        if cmd in ('req_del', 'req_clear'):
            current = {r['id'] for r in s.reqs}
            for song in s.songs:
                if song.get('req_ids'):
                    song['req_ids'] = [rid for rid in song['req_ids'] if rid in current]
        s.dirty = True
        self.emit('reqs', s.reqs)

    def song_cmd(self, cmd, sid='', text='', options=None):
        options = options or {}
        s = self.state
        old_songs, old_reqs = copy.deepcopy(s.songs), copy.deepcopy(s.reqs)
        result = ''
        def linked(x, done):
            for r in s.reqs:
                if r['id'] in x.get('req_ids', []):
                    r['done'] = done
        def finish(x):
            self.songbook_add(x['name'], sung=True, performance=x['id'])
            x.update(done=True, done_at=int(time.time()))
            x.pop('now', None)
            linked(x, True)
        def advance():
            if not any(x.get('now') for x in s.songs):
                nxt = next((x for x in s.songs if not x['done']), None)
                if nxt:
                    nxt['now'] = True
        try:
            if cmd == 'song_add':
                added, blocked = 0, []
                for name in [x.strip()[:80] for x in re.split(r'[\r\n]+', text) if x.strip()][:50]:
                    # 「暂停点歌」阻止观众请求入队，主播仍可手动安排。
                    rid = str(options.get('req_id', ''))
                    if rid and self.songbook.get(name, {}).get('available') is False:
                        blocked.append(name)
                        continue
                    x = next((x for x in s.songs if x['name'].casefold() == name.casefold() and not x['done']), None)
                    if x is None:
                        if len(s.songs) >= 200:
                            raise ValueError('歌单已满，请先清理已唱歌曲')
                        x = {'id': uuid.uuid4().hex, 'name': name, 'done': False, 'req_ids': []}
                        s.songs.append(x)
                        added += 1
                        self.songbook_add(name)
                    # 同名未完成请求关联到本次演唱；重复点击＋不会重复排歌。
                    self.link_requests(x)
                result = f'新增 {added} 首，重复歌曲已合并'
                if blocked:
                    result += '；暂停点歌：' + '、'.join(blocked)
            elif cmd == 'song_done':
                x = next((x for x in s.songs if x['id'] == sid), None)
                if not x:
                    raise ValueError('歌曲已不在歌单中，请刷新后重试')
                done = options.get('done', not x['done'])
                if not isinstance(done, bool):
                    raise ValueError('无效的完成状态')
                if done and not x['done']:
                    was_now = x.get('now')
                    finish(x)
                    if was_now or not any(y.get('now') for y in s.songs):
                        advance()
                elif not done and x['done']:
                    x['done'] = False
                    x.pop('done_at', None)
                    linked(x, False)
                result = '已完成并同步点歌请求' if done else '已撤销完成；重复勾选不会重复增加演唱次数'
            elif cmd == 'song_next':
                current = next((x for x in s.songs if x.get('now')), None)
                current_id = current['id'] if current else None
                if 'expected_now' in options and options['expected_now'] != current_id:
                    raise ValueError('正在唱的歌曲已切换，请核对后再操作')
                if current:
                    finish(current)
                advance()
                result = '已切换下一首' if any(x.get('now') for x in s.songs) else '歌单已唱完'
            elif cmd == 'song_now':
                target = next((x for x in s.songs if x['id'] == sid), None)
                if not target or target['done']:
                    raise ValueError('请先撤销已唱状态，或添加一次新的演唱')
                enabled = not target.get('now')
                for x in s.songs:
                    x.pop('now', None)
                if enabled:
                    target['now'] = True
            elif cmd == 'song_move':
                i = next((i for i, x in enumerate(s.songs) if x['id'] == sid), -1)
                direction = options.get('direction')
                if i >= 0 and 'before' in options:
                    # 拖动排序：挪到某一首前面（before 是那首的编号；空的就是挪到没唱的最后）。只在没唱、也不是正在唱的歌之间挪
                    moving = s.songs[i]
                    if moving['done'] or moving.get('now'):
                        raise ValueError('无效的排序操作')
                    target = str(options.get('before') or '')
                    rest = [x for x in s.songs if x is not moving]
                    if target:
                        at = next((j for j, x in enumerate(rest) if x['id'] == target and not x['done'] and not x.get('now')), -1)
                        if at < 0:
                            raise ValueError('无效的排序操作')
                    else:
                        pending = [j for j, x in enumerate(rest) if not x['done'] and not x.get('now')]
                        at = pending[-1] + 1 if pending else len(rest)
                    rest.insert(at, moving)
                    s.songs = rest
                    direction = 0
                elif i < 0 or direction not in (-1, 1):
                    raise ValueError('无效的排序操作')
                indexes = [j for j, x in enumerate(s.songs) if not x['done'] and not x.get('now')]
                if direction and i in indexes:
                    at = indexes.index(i) + direction
                    if 0 <= at < len(indexes):
                        j = indexes[at]
                        s.songs[i], s.songs[j] = s.songs[j], s.songs[i]
            elif cmd == 'song_del':
                s.songs = [x for x in s.songs if x['id'] != sid]
            elif cmd == 'song_clear':
                s.songs = [] if sid == 'all' else [x for x in s.songs if not x['done']]
            for r in s.reqs:
                if r.get('queued_id') and not any(x['id'] == r['queued_id'] for x in s.songs):
                    r.pop('queued_id', None)
            s.dirty = True
            if s.file and s.save() is False:
                raise OSError('歌单保存失败')
        except (ValueError, OSError):
            s.songs, s.reqs = old_songs, old_reqs
            s.dirty = True
            raise
        self.emit('songs', self.songs_view())
        self.emit('reqs', s.reqs)
        return result


    def enter(self, uid, name, face='', kind='enter', guard=0, plat=''):
        face = validation.safe_url(face)
        if not self.valid_event('enter', {'uid': uid, 'name': name, 'face': face, 'kind': kind, 'guard': guard}):
            return
        s = self.state
        if kind == 'like':  # 点赞（2026-11-19）：同一个人 5 分钟内只记一次，免得连点刷屏
            if any(e['uid'] == uid and e['kind'] == 'like' and time.time() - e['t'] < 300 for e in s.enters[-100:]):
                return
        if kind == 'enter':
            # 机器人的号每 10 分钟查一次房管状态，B 站会把这当成进房，不记
            if uid in s.bot_uids:
                return
            # 同一个人 10 分钟内重复进房（掉线重连、刷新页面）只记一次；舰长两条消息（普通进房 + 进场特效）也在这里合成一条
            for e in reversed(s.enters[-100:]):
                if e['uid'] == uid and e['kind'] == 'enter' and time.time() - e['t'] < 600:
                    if guard and not e.get('guard'):
                        e['guard'] = guard
                        s.touch_user(uid, name, face, guard=guard)
                        self.emit('enter_update', e)
                    return
        if kind == 'follow':
            s.stats['follows'] = s.stats.get('follows', 0) + 1
        item = {'t': int(time.time()), 'uid': uid, 'name': name, 'face': face, 'kind': kind, 'guard': guard}
        if plat in PLAT_NAMES:
            item['plat'] = plat
        s.enters.append(item)
        del s.enters[:-200]
        s.touch_user(uid, name, face, enter=1 if kind == 'enter' else 0, guard=guard)
        self.bus.publish('enter', item)
        self.emit('enter', item, uc=len(s.users))

    def room_warn(self, kind, msg):
        """超管警告 / 切断（2026-11-19）：B 站发 WARNING / CUT_OFF，网页上红条提醒（只给管理身份）。"""
        item = {'t': int(time.time()), 'kind': 'cut' if kind == 'CUT_OFF' else 'warn', 'msg': str(msg or '')[:200]}
        self.state.warns = (getattr(self.state, 'warns', None) or [])[-19:] + [item]
        log.warning('B 站%s：%s', '切断了直播' if item['kind'] == 'cut' else '超管警告', item['msg'])
        self.emit_admin('warn', item)

    def gift(self, uid, name, face, gift_name, num, yuan, img='', guard=0, blind='', gift_id=0, plat=''):
        face, img = validation.safe_url(face), validation.safe_url(img)
        if not img and gift_name in GIFT_BY_NAME:  # 演示模式的假礼物没有图：按名字补上
            img = GIFT_BY_NAME[gift_name][0]
        anim = (GIFT_BY_ID.get(gift_id) or ('', ''))[1] or GIFT_ANIM.get(img) or (GIFT_BY_NAME.get(gift_name) or ('', ''))[1]
        if not self.valid_event('gift', {'uid': uid, 'name': name, 'face': face, 'gift_name': gift_name, 'num': num, 'yuan': yuan,
                                         'img': img, 'guard': guard, 'blind': blind}):
            return
        s = self.state
        # 连击的同一个礼物合并成一条
        last = s.gifts[-1] if s.gifts else None
        if last and last['uid'] == uid and last['gift'] == gift_name and last.get('blind', '') == blind \
                and time.time() - last['t'] < 8:
            last['num'] += num
            last['yuan'] = round(last['yuan'] + yuan, 2)
            last['t'] = int(time.time())
            item = last
        else:
            item = {'id': f'{uid}-{time.time():.3f}', 't': int(time.time()), 'uid': uid, 'name': name,
                    'face': face, 'gift': gift_name, 'num': num, 'yuan': round(yuan, 2), 'img': img, 'guard': guard,
                    'blind': blind}
            if anim:
                item['anim'] = anim
            if plat in PLAT_NAMES:
                item['plat'] = plat
            fx, fxj = gift_fx(gift_id, gift_name)
            if fx:
                item['fx'], item['fxj'] = fx, fxj  # 官方满屏特效（大礼物特效用）
            if self.offline_now():
                item['source'] = '下播'  # 下播期间送的：页面上标出来，开播清零时留下
            s.gifts.append(item)
            del s.gifts[:-1000]
        st = s.gift_stats.setdefault(blind + '爆出' + gift_name if blind else gift_name, {'num': 0, 'yuan': 0.0})
        st['num'] += num
        st['yuan'] = round(st['yuan'] + yuan, 2)
        s.flow['gift'] = round(s.flow['gift'] + yuan, 2)
        s.touch_user(uid, name, face, spend=yuan, guard=guard)
        self.bus.publish('gift', item)
        self.emit('gift', {'item': item, 'flow': s.flow, 'user': self.user(uid)})

    def tags_changed(self):
        self.state.manual_bots = list(self.tags.bots)
        set_bots(self.state)
        self.emit('tags', {'tags': self.tags.view(), 'bot_uids': self.state.bot_uids})

    def xrooms_set(self, c):
        self.xrooms = validation.xrooms({'open': c.get('open', False), 'rooms': c.get('rooms', [])})
        if self.xrooms_file:
            write_json(self.xrooms_file, self.xrooms)
        self.emit('xrooms', self.xrooms)
        return ('普通链接可以切换直播间' if self.xrooms['open'] else '普通链接不能切换直播间了') + f"（名单里 {len(self.xrooms['rooms'])} 个）"

    def xroom_listed(self, *rooms):
        ok = {xroom_key(r) for r in self.xrooms['rooms']}
        return any(r in ok for r in rooms if r)

    def xroom_allowed(self, *rooms):
        ok = {xroom_key(r) for r in self.xrooms['rooms']} if self.xrooms['open'] else set()
        return any(r in ok for r in rooms if r)

    def tpre_set(self, rows):
        self.title_presets = validation.title_presets(rows)
        if self.tpre_file:
            write_json(self.tpre_file, self.title_presets)
        self.emit_admin('tpre', self.title_presets)
        return '已保存'

    def offline_now(self):
        """现在是不是下播期间。刚重启还没问到开播状态时，这场已经下播存过历史也算下播（以前这种会漏标）。"""
        s = self.state
        live = s.room.get('live')
        return live == 0 or (live is None and s.summarized and bool(s.settled_at))

    def offline_thank(self, gid, done):
        """在 data/offline/<房间>/*.json 里找这一条，改「已感谢」。找到就返回 True。
        2026-11-21 修：同一条可能在好几个下播记录里都有（换场时又另存了一份），每个文件里的都改，不只改第一个。"""
        d = os.path.join(DIR, 'data', 'offline', str(self.state.room_id))
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return False
        found = False
        for n in names:
            p = os.path.join(d, n)
            try:
                with open(p, encoding='utf-8') as f:
                    off = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(off, dict):
                continue
            hit = False
            for k in ('gifts', 'guards'):
                for x in off.get(k) or []:
                    if isinstance(x, dict) and str(x.get('id')) == gid:
                        if done:
                            x['thanked'] = True
                        else:
                            x.pop('thanked', None)
                        hit = True
            if hit:
                write_json(p, off)
                found = True
        return found

    def gift_thank_cmd(self, command):
        """礼物 / 上舰「已感谢」打勾（2026-11-18）：记在那一条上，所有管理设备同步。"""
        s = self.state
        gid, done = str(command['id']), bool(command['done'])
        item = next((x for x in reversed(s.gifts + s.guards) if str(x.get('id')) == gid), None)
        if item is None:
            # 2026-11-20：下播期间的礼物 / 上舰存在 data/offline 里，也能打勾
            if self.offline_thank(gid, done):
                self.emit_admin('gift_thanked', {'id': gid, 'done': done})
                return '已同步'
            raise ValueError('这条礼物不在本场里，请刷新后再试')
        if bool(item.get('thanked')) != done:
            if done:
                item['thanked'] = True
            else:
                item.pop('thanked', None)
            s.dirty = True
            s.save()
            self.emit_admin('gift_thanked', {'id': gid, 'done': done})
        # 2026-11-21 修：下播收到的这一条，换场时可能已经另存进下播记录；那边也一起改，不然「下播期间」页刷新又变回去
        if item.get('source') == '下播':
            self.offline_thank(gid, done)
        return '已同步'

    def sc_read_cmd(self, command):
        s = self.state
        s.prune_sc_read()
        current = {str(row['id']) for row in s.scs}
        old = list(s.sc_read)
        if command['cmd'] == 'sc_read_all':
            updated = validation.clean_sc_read([row['id'] for row in s.scs], s.scs)
        else:
            sid = validation.sc_id(command.get('id'))
            read = validation.boolean(command.get('read'), '已读状态')
            if sid not in current:
                raise ValueError('这条 SC 不在本场里，请刷新后再试')
            updated = list(old)
            if read and sid not in updated:
                if len(updated) >= 5000:
                    raise ValueError('本场已读记录已满，请先整理本场')
                updated.append(sid)
            elif not read:
                updated = [value for value in updated if value != sid]
        if updated != old:
            s.sc_read, s.dirty = updated, True
            if s.save() is False:
                s.sc_read, s.dirty = old, True
                raise OSError('SC 已读状态未能保存')
            # 包括发命令的那台在内，所有管理设备收到同一份完整列表。
            self.emit_admin('sc_read', list(updated))
        return 'SC 已读状态已同步'

    def super_chat(self, sc_id, uid, name, face, price, text, guard=0, end=0, recovered=False, start=0, icon=''):
        face = validation.safe_url(face)
        icon = validation.safe_url(icon) if icon else ''  # B 站 500 元以上的 SC 右上角那张装饰图（2026-11-21，主页面照 B 站画）
        if not self.valid_event('sc', {'sc_id': sc_id, 'uid': uid, 'name': name, 'face': face, 'price': price, 'text': text, 'guard': guard, 'end': end}):
            return
        s = self.state
        if any(str(x['id']) == str(sc_id) for x in s.scs):
            return  # 同一条 SC 偶尔会推两次
        now = int(time.time())
        item = {'id': sc_id, 't': now, 'uid': uid, 'name': name, 'face': face,
                'price': price, 'text': text, 'guard': guard,
                'end': int(end) if end and end > now else now + sc_seconds(price)}  # 置顶到什么时候
        if icon:
            item['icon'] = icon
            tier = '2000' if price >= 2000 else '1000' if price >= 1000 else '500' if price >= 500 else ''
            if tier and self.sc_icons.get(tier) != icon:  # 各档的装饰图记下来，以前没带图的 SC 也能补上（2026-11-21）
                self.sc_icons[tier] = icon
                if self.sc_icons_file:
                    try:
                        write_json(self.sc_icons_file, self.sc_icons)
                    except OSError:
                        pass
        if recovered:
            item.update(t=start, end=int(end), recovered=True, source='补录')
        s.prune_sc_read()  # 先清掉旧的孤立编号，补录的新 SC 仍默认未读。
        s.scs.append(item)
        s.flow['sc'] = round(s.flow['sc'] + price, 2)
        s.touch_user(uid, name, face, spend=price, guard=guard)
        self.bus.publish('sc', item)
        self.emit('sc', {'item': item, 'flow': s.flow, 'user': self.user(uid)})
        return True

    def guard_buy(self, uid, name, level, num, yuan, unit='月', op='', days=0):
        """op：开通 / 续费（2026-11-20，跟 B 站一样显示）；days：B 站说的「今天是 TA 陪伴主播的第几天」，没有就是 0。"""
        if not self.valid_event('guard', {'uid': uid, 'name': name, 'level': level, 'num': num, 'yuan': yuan, 'unit': unit}):
            return
        s = self.state
        item = {'id': uuid.uuid4().hex, 't': int(time.time()), 'uid': uid, 'name': name, 'level': level,
                'level_name': GUARD_NAMES.get(level, '舰长'), 'num': num, 'unit': unit, 'yuan': round(yuan, 2)}
        face = (s.users.get(str(uid)) or {}).get('face') or ''
        if face:
            item['face'] = face  # 上舰消息不带头像（2026-11-25）：认得这个人就用他的头像，不认得就去 B 站名片查
        else:
            self.need_face(uid)
        if op in ('开通', '续费'):
            item['op'] = op
        if isinstance(days, int) and 0 < days < 100000:
            item['days'] = days
        if self.offline_now():
            item['source'] = '下播'
        if level in GUARD_FX:
            item['fx'], item['fxj'] = GUARD_FX[level]  # 官方上舰特效（礼物栏大特效用）
        s.guards.append(item)
        s.flow['guard'] = round(s.flow['guard'] + yuan, 2)
        s.touch_user(uid, name, spend=yuan, guard=level)
        self.guardbook.bought(uid, level, num, unit)
        self.guard_wake.set()
        self.bus.publish('guard', item)
        self.emit('guard', {'item': item, 'flow': s.flow, 'user': self.user(uid)})

    def room_update(self, **kw):
        try:
            kw = validation.room_values(kw)
        except ValueError as e:
            log.warning('跳过无效房间状态：%s', e)
            return
        s = self.state
        s.room.update(kw)
        st = s.stats
        if kw.get('online'):
            st['peak_online'] = max(st.get('peak_online', 0), kw['online'])
        if kw.get('watched'):
            st['watched'] = kw['watched']
        if kw.get('likes'):
            st['likes'] = kw['likes']
        if s.room.get('live'):
            s.was_live = True
            for k in ('title', 'area'):
                if kw.get(k):
                    s.meta[k] = kw[k]
        s.dirty = True
        self.emit('room', s.room)


class MemState(State):
    """切到别的直播间时用的「本场数据」（2026-11-20）：只放内存，不读也不写 data/房间号.json。"""

    def __init__(self, room_id):
        self.room_id = room_id
        self.file = None
        self.room = {}
        self.bot_uids = []
        self.songs = []
        self.reset()
        self.dirty = False


class NullHistory:
    """别的直播间不存历史。"""
    def list(self):
        return []

    def get(self, sid):
        return None

    def save(self, summary):
        pass

    def has_dm(self, sid):
        return False

    def dm_file(self, sid):
        return os.devnull


def xroom_key(r):
    """切房名单里一个房间的「钥匙」：B 站就是房间号（数字），别的平台是 平台:房间号（2026-11-26）"""
    return f"{r['plat']}:{r['room']}" if r.get('plat') else r['room']


class SideHub(Hub):
    """切到别的直播间（2026-11-20 用户要整页切过去）：和主播那套一样收弹幕、礼物、SC、上舰、进房，
    但只在内存里，只发给切过去的那几个页面；不结算、不存历史、不存下播记录，主播的记录、OBS、朗读都不碰。"""
    side = True

    def settle(self, reason, end=None, retry=False):
        return None

    def close_broadcast(self, reason, end=None):
        return None

    def save_offline(self):
        return None

    def new_session(self, reason):
        return None


def set_bots(state, base=None):
    """哪些号算机器人：连直播间用的那个号（接了 bot_say_url 时）+ 主播自己在观众卡片里标的（2026-11-26）"""
    if base is not None:
        state.base_bots = list(base)
    state.bot_uids = sorted(set(getattr(state, 'base_bots', None) or []) | set(getattr(state, 'manual_bots', None) or []))


async def watch_login(session, state):
    """机器人重新登录后（登录文件变了），这边也换上新的登录信息。"""
    mtime = 0
    while True:
        try:
            m = os.path.getmtime(LOGIN_FILE)
            if mtime and m != mtime:
                cookie = load_cookie()
                session.cookie_jar.update_cookies(make_cookies(cookie))
                set_bots(state, [u for u in [uid_of(cookie)] if u] if BOT_SAY_URL else [])  # 2026-11-25：只有另外接了机器人（bot_say_url）才算机器人
                log.info('机器人的登录信息更新了，已换上')
            mtime = m
        except OSError:
            pass
        await asyncio.sleep(300)


async def watch_bili(hub, session):
    """两件事：电脑跟 B 站的弹幕连接还在不在；机器人那个 B 站号的登录还有没有效。"""
    n = 0
    while True:
        # 断网时 blivedm 连不上会直接放弃（InitError），不会自己再试；这里发现它停了就重新启动，
        # 网恢复后十几秒内自己连回来（2026-11-10 断网后弹幕一直没恢复，就是这个原因）
        client = getattr(hub, 'client', None)
        if client is not None and not client.is_running and time.monotonic() >= hub.restart_after:
            hub.restart_count += 1
            hub.restart_after = time.monotonic() + connection_recovery.retry_delay(hub.restart_count)
            log.warning('B 站弹幕连接停了，重新连接')
            try:
                client.start()
            except Exception as e:
                log.warning('重新连接失败：%s', e)
        now = time.time()
        ok = now - hub.bili_seen < 75
        if hub.state.outages and hub.state.outages[-1].get('up_at') is None and not hub.bili_message_seen:
            ok = False
        if connection_recovery.connection_state(hub, ok, now):
            if ok:
                hub.restart_count = 0
                log.info('跟 B 站的连接恢复了')
            else:
                log.warning('超过 75 秒没收到 B 站消息，连接可能断了（会自动重连）')
        # 最后一道保险：连续 3 分钟连不上，就退出让守护把整个程序重开一遍（本场数据已存盘，不会丢）。
        # 10 分钟内最多重开一次，免得真的没网时一直重启。
        if not ok and now - hub.bili_seen > 180:
            mark = os.path.join(DIR, 'data', 'selfrestart.txt')
            try:
                last = os.path.getmtime(mark)
            except OSError:
                last = 0
            if now - last > 600:
                log.warning('连续 3 分钟连不上 B 站，自动重启程序')
                hub.state.dirty = True
                saved = hub.state.save()
                logged = hub.dmlog.flush()
                if saved and logged:
                    try:
                        with open(mark, 'w', encoding='utf-8') as f:
                            f.write(time.strftime('%Y-%m-%d %H:%M:%S'))
                    except OSError as e:
                        log.warning('保存失败，推迟自动重启：%s', e)
                    else:
                        logging.shutdown()
                        os._exit(3)
        if n % 60 == 0:  # 机器人号是不是这个直播间的房管（禁言要用），10 分钟查一次
            try:
                async with session.get('https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByUser'
                                       f'?room_id={hub.state.room_id}&from=0', timeout=aiohttp.ClientTimeout(total=15)) as r:
                    d = (await r.json(content_type=None)).get('data') or {}
                adm = bool((d.get('badge') or {}).get('is_room_admin'))
                if hub.state.room.get('bot_admin') != adm:
                    hub.room_update(bot_admin=adm)
            except Exception as e:
                log.warning('查房管状态失败：%s', e)
        if n % 30 == 0:  # 登录每 5 分钟查一次
            try:
                async with session.get('https://api.bilibili.com/x/web-interface/nav',
                                       timeout=aiohttp.ClientTimeout(total=15)) as r:
                    d = (await r.json(content_type=None)).get('data') or {}
                login = bool(d.get('isLogin'))
                if login and (hub.state.room.get('bot_name') != d.get('uname') or hub.state.room.get('bot_face') != d.get('face')):
                    hub.room_update(bot_name=d.get('uname', ''), bot_face=d.get('face', ''))
                if hub.state.room.get('login_ok') != login:
                    if not login:
                        log.warning('机器人的 B 站登录失效了，弹幕用户名会被打码')
                    hub.room_update(login_ok=login)
            except Exception as e:
                log.warning('查登录状态失败：%s', e)
        n += 1
        await asyncio.sleep(10)


IMG_CACHE = os.path.join(DIR, 'data', 'imgcache')
GEQU_DIR = ''  # 歌切合集的文件夹（config.json 的 gequ_dir，可选）
# 看板娘（2026-11-26）：设置 → 更多 → 看板娘 里换成自己的图。网页先缩好这几个尺寸的 PNG 传上来，存在 data/mascot；
# 没换过就用 static/art 里默认的图标。网页、窗口、任务栏图标都走 /art/icon-{尺寸}.png，两种都认
MASCOT_SIZES = (32, 64, 192, 256, 512)
MASCOT_MAX = 1024 * 1024
MASCOT_DIR = os.path.join(DIR, 'data', 'mascot')


def mascot_ver(folder):
    """换过的看板娘图最后一次改的时间（网页拿它刷新图标）；没换过是 0"""
    times = []
    for n in MASCOT_SIZES:
        try:
            times.append(int(os.path.getmtime(os.path.join(folder, f'icon-{n}.png')) * 1000))  # 毫秒：5 张图一秒内传完，按秒算会重名
        except OSError:
            pass
    return max(times, default=0)


def clean_img_cache(days=30):
    try:
        old = time.time() - days * 86400
        for path in retention.iter_plain_files(Path(IMG_CACHE), re.compile(r'[0-9a-f]{40}\.webp')):
            if path.stat().st_mtime < old:
                retention.remove_data_file(path, '图片缓存超过保留期')
    except OSError:
        pass


class Alerts:
    """掉线提醒（2026-11-12）：哪一环断了超过一会儿就发 Discord，好了再说一声。
    同一件事断着只提醒一次；状态存在 data/alerts.json，程序重启、电脑重启后也接得上（恢复时会说断了多久）。
    当时连网都断了发不出去的，等恢复时一起说「刚才断了多久」。"""

    def __init__(self, session, persist=True):
        self.session = session
        self.file = os.path.join(DIR, 'data', 'alerts.json') if persist else None
        self.state = {}
        self.unsaved = False
        if self.file:
            try:
                with open(self.file, encoding='utf-8') as f:
                    self.state = json.load(f)
            except (OSError, ValueError):
                pass

        self.state = validation.mapping(self.state, lambda k, r: {
            'since': validation.number(r['since'], '提醒时间', 0, validation.MAX_TIME),
            'sent': validation.boolean(r['sent'], '提醒状态')}, 16)

    def _save(self):
        if not self.file:
            return
        try:
            write_json(self.file, self.state)
            self.unsaved = False
        except OSError as e:
            # 数据盘写不进时仍须发出存档告警；磁盘恢复后补存发送状态。
            self.unsaved = True
            log.warning('提醒状态保存失败，稍后重试：%s', e)

    async def send(self, text):
        url = DISCORD_WEBHOOK
        if not url and DISCORD_WEBHOOK_FILE:
            try:
                with open(DISCORD_WEBHOOK_FILE, encoding='utf-8-sig') as f:
                    url = str(json.load(f).get('discord_webhook', '') or '')
            except (OSError, ValueError, AttributeError):
                url = ''
        if not url:
            return False
        try:
            async with self.session.post(url, json={'username': BRAND['name'], 'content': text},
                                         timeout=aiohttp.ClientTimeout(total=15)) as r:
                ok = r.status < 300
        except (aiohttp.ClientError, asyncio.TimeoutError):
            ok = False
        log.info('掉线提醒%s：%s', '已发' if ok else '没发出去', text)
        return ok

    async def check(self, kind, bad, after, down_text, up_text):
        """bad：现在是不是坏的；after：坏了多少秒才提醒；down_text / up_text：传入分钟数，返回要发的话。"""
        if self.unsaved:
            self._save()
        now, st = time.time(), self.state.get(kind)
        mins = lambda: max(1, round((now - st['since']) / 60))
        if bad:
            if not st:
                st = self.state[kind] = {'since': now, 'sent': False}
                self._save()
            if not st['sent'] and now - st['since'] >= after and await self.send(down_text(mins())):
                st['sent'] = True
                self._save()
        elif st:
            # 恢复了：提醒过的、或者断得够久（当时没发出去）的，都说一声
            if st['sent'] or now - st['since'] >= after:
                if not await self.send(up_text(mins())):
                    return  # 恢复提醒未发出去，等下一轮再试
            del self.state[kind]
            self._save()

    async def check_archive(self, state, dmlog):
        bad = bool(state.archive_pending or getattr(dmlog, 'repair_write', False))
        await self.check('archive', bad, 300,
                         lambda m: f'⚠️ {BRAND["name"]}存档写入已失败约 {m} 分钟，正在重试。请检查磁盘空间和权限。',
                         lambda m: f'✅ {BRAND["name"]}存档写入恢复（中断约 {m} 分钟）。')


SAME_SESSION_SEC = 300  # 断流后这么多秒内又开播算同一场（跟 QQ 机器人一样 5 分钟，2026-11-23）
SONGBOOK_MAX = 10000  # 歌本 / 曲库最多记多少首（跟曲库导入的上限一致）
# 主页面拆成了 index.html + static/app/ 下的样式和几段脚本（2026-11-13）
APP_FILES = ('app/main.css', 'app/icons.js', 'app/core.js', 'app/render.js', 'app/people.js', 'app/voice.js', 'app/songs.js', 'app/news.js', 'app/ws.js', 'app/ui.js')
PAGES = ('index.html', 'obs.html', 'obs-songs.html', 'obs-setup.html', 'obs-lyrics.html', 'workbench.js', 'workbench.css') + APP_FILES


def static_path(rel):
    """static/ 下的一个文件：包里有同名的就用包里的（2026-11-26）"""
    if PACK:
        p = os.path.join(PACK, 'static', rel)
        if os.path.isfile(p):
            return p
    return os.path.join(DIR, 'static', rel)


def pack_file(rel):
    """只在包里找（ext/ 下的额外样式和脚本只有包里才有）"""
    if not PACK:
        return ''
    p = os.path.join(PACK, 'static', rel)
    return p if os.path.isfile(p) else ''


EXT_PAGES = ('index', 'obs', 'obs-setup', 'obs-songs', 'obs-music', 'obs-lyrics')


def page_vers():
    """每个网页文件最后改动的时间。网页拿它判断自己是不是旧版：上线新版后页面和 OBS 浏览器源会自己刷新。"""
    out = {}
    for n in PAGES + tuple(f'ext/{p}.{e}' for p in EXT_PAGES for e in ('css', 'js')):
        try:
            out[n] = int(os.path.getmtime(static_path(n)))
        except OSError:
            pass
    # 包里的额外样式 / 脚本改了，用到它的网页也算新版（自己刷新）
    for p in EXT_PAGES:
        ext = [out[k] for k in (f'ext/{p}.css', f'ext/{p}.js') if k in out]
        if ext and f'{p}.html' in out:
            out[f'{p}.html'] = max(out[f'{p}.html'], *ext)
    return out


def brand_view():
    return {'name': BRAND['name'], 'short': BRAND['short'], 'medal': BRAND.get('medal', '粉丝团'), 'host': HOST_PATH, 'pack': bool(PACK)}


def render_page(name):
    """读一个网页：填上 ?v= 版本号、换上品牌名、加上包里的额外样式和脚本（2026-11-26）"""
    with open(static_path(name + '.html'), encoding='utf-8') as f:
        html = f.read()
    v = page_vers()
    html = re.sub(r'((?:app/[\w-]+|workbench)\.(?:js|css))\?v=[\w.-]+', lambda m: f"{m.group(1)}?v={v.get(m.group(1), 0)}", html)
    if BRAND['name'] != '雾幕':
        nm = BRAND['name']
        html = html.replace('<title>雾幕', '<title>' + nm).replace('· 雾幕</title>', '· ' + nm + '</title>').replace('<h1>雾幕<', '<h1>' + nm + '<')
    tags = ['<script>window.BRAND=' + json.dumps(brand_view(), ensure_ascii=False).replace('</', '<\\/') + '</script>']
    if pack_file(f'ext/{name}.css'):
        tags.append(f'<link rel="stylesheet" href="/static/ext/{name}.css?v={v.get(f"ext/{name}.css", 0)}">')
    if pack_file(f'ext/{name}.js'):
        tags.append(f'<script src="/static/ext/{name}.js?v={v.get(f"ext/{name}.js", 0)}"></script>')
    return html.replace('</head>', ''.join(tags) + '</head>', 1)


BACKUP_SKIP = ('imgcache', 'douyin-browser', 'update', 'mascot-tmp')  # 缓存和临时的，不用备份、恢复时也不动
BACKUP_NAME = re.compile(r'data-\d{8}(?:-\d{6}-[\w-]{1,12})?\.zip')


def backup_dir():
    return os.path.join(DIR, '备份', '数据')


def backup_data(keep=14, tag=''):
    """把 data 文件夹打成一个压缩包放到「备份/数据/」。不带 tag 是每天自动的那份（一天一份，留最近 keep 份，今天的已经有了就不做）；
    带 tag（手动 / 更新前 / 恢复前，2026-11-26）每次都做一份，这种留最近 10 份。"""
    out_dir = backup_dir()
    out = os.path.join(out_dir, time.strftime(f'data-%Y%m%d-%H%M%S-{tag}.zip' if tag else 'data-%Y%m%d.zip'))
    if os.path.exists(out) and not tag:
        return None
    os.makedirs(out_dir, exist_ok=True)
    src = os.path.join(DIR, 'data')
    tmp = out + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(src):
            if root == src:
                dirs[:] = [d for d in dirs if d not in BACKUP_SKIP]
            for n in files:
                if n.endswith('.tmp'):
                    continue
                p = os.path.join(root, n)
                try:
                    z.write(p, os.path.relpath(p, src))
                except OSError:
                    pass  # 正好在写的文件，下次再备
    os.replace(tmp, out)
    old = sorted(n for n in os.listdir(out_dir) if re.match(r'^data-\d{8}\.zip$', n))
    for n in old[:-keep]:
        os.remove(os.path.join(out_dir, n))
    tagged = sorted(n for n in os.listdir(out_dir) if re.match(r'^data-\d{8}-\d{6}-.+\.zip$', n))
    for n in tagged[:-10]:
        os.remove(os.path.join(out_dir, n))
    return out


def list_backups():
    d = backup_dir()
    try:
        names = [n for n in os.listdir(d) if BACKUP_NAME.fullmatch(n)]
    except OSError:
        return []
    rows = []
    for n in names:
        try:
            st = os.stat(os.path.join(d, n))
            rows.append({'name': n, 'size': st.st_size, 't': int(st.st_mtime)})
        except OSError:
            pass
    return sorted(rows, key=lambda r: -r['t'])


RESTORE_FILE = 'restore-pending.json'


def apply_pending_restore():
    """启动时：页面上点过「从这份恢复」，先把现在的 data 再备份一份（恢复前），再把那份解压回来（2026-11-26）"""
    data = os.path.join(DIR, 'data')
    flag = os.path.join(data, RESTORE_FILE)
    if not os.path.exists(flag):
        return None
    try:
        with open(flag, encoding='utf-8') as f:
            name = str(json.load(f).get('name', ''))
        os.remove(flag)
        src = os.path.join(backup_dir(), name)
        if not BACKUP_NAME.fullmatch(name) or not os.path.isfile(src):
            raise ValueError(f'找不到备份 {name}')
        with zipfile.ZipFile(src) as z:
            if z.testzip() is not None:
                raise ValueError(f'备份 {name} 坏了')
            for info in z.infolist():
                p = os.path.normpath(info.filename)
                if p.startswith('..') or os.path.isabs(p):
                    raise ValueError(f'备份 {name} 里有不对的路径')
            backup_data(tag='恢复前')
            for n in os.listdir(data):
                if n in BACKUP_SKIP:
                    continue
                p = os.path.join(data, n)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            z.extractall(data)
        return name
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        logging.getLogger('danmaku').warning('恢复数据没成功：%s', e)
        return False


async def maintain_data(hub):
    """在房间外的后台线程扫描和打包；更新当前状态、历史索引时回到服务线程。"""
    s = hub.state
    room = str(s.room_id)
    data = Path(DIR) / 'data'
    if not retention.is_plain(data, directory=True):
        return
    index = hub.history._index()
    protected = {s.archive_id}
    if s.archive_pending:
        protected.add(s.archive_pending['id'])
    indexed = {row['id']: row for row in index}

    def scan():
        retention.weekly_cleanup(DIR, write_json)
        # 尚未确认归档的遗留分段可能还需依赖历史或下播文件核对，先保留这些副本。
        unresolved = retention.prune_dmlog(data, room, indexed, protected)
        keep = protected | unresolved
        retention.prune_offline(data, room, keep)
        retention.prune_accounts(data / 'accounts')
        clean_img_cache()


    await asyncio.to_thread(scan)
    await history_maintenance.maintain(hub, DIR, write_json)
    hub.guardbook.prune()


async def daily_backup(hub):
    """每天自动备份一次数据（启动时今天还没备就先备一份），在后台线程里压缩，不卡弹幕。"""
    while True:
        try:
            await maintain_data(hub)
        except (OSError, ValueError) as e:
            log.warning('数据维护将在下次重试：%s', e)
        try:
            out = await asyncio.get_event_loop().run_in_executor(None, backup_data)
            if out:
                log.info('今天的数据备份好了：%s', out)
        except Exception as e:
            log.warning('数据备份失败：%s', e)
        await asyncio.sleep(1800)


DEMO_NAMES =['雾里看花', '冬天的鱼', '橘子汽水', '小鱼干', '晚安主播', '雪糕不化', '路过的舰长', '今天也想听歌']


DEMO_ROOM = 1000001  # 演示模式假装的房间号


async def demo_feed(hub):
    """演示模式：随机造弹幕/礼物/SC/上舰，用来看网页样式。"""
    names = DEMO_NAMES
    texts = ['主播晚上好～', '这首好好听！', '哈哈哈哈哈', '唱晴天吗', '来了来了', '今天好可爱', '打卡', '想听稻香', '点歌 晴天']
    hub.room_update(title='【歌回】今天唱点冬天的歌', live=1, area='唱见电台', watched=3821, online=126, likes=5120,
                    bili_ok=True, login_ok=True, room_real=DEMO_ROOM,
                    top=[{'uid': i, 'name': n, 'face': '', 'score': 1000 - i * 90, 'guard': 3 if i < 2 else 0}
                         for i, n in enumerate(names[:6])])
    i = 0
    while True:
        i += 1
        n = random.choice(names)
        uid = names.index(n) + 1000
        r = random.random()
        if r < 0.55:
            hub.danmaku(uid, n, '', random.choice(texts), '粉丝团' if uid % 4 else '别家', 3 + uid % 22,
                        3 if n == '路过的舰长' else 0, n == '小鱼干', '', 12345 if uid % 4 == 0 else DEMO_ROOM,
                        medal_lit=0 if n in ('雾里看花', '冬天的鱼') else 1,  # 演示：有两个人的牌子是灰的
                        wealth=(uid * 7) % 40 if uid % 3 else 0, reply=random.choice(['', '', '', '小鱼干']))
            if random.random() < 0.15:
                hub.enter(uid, n, '', 'like', 0)
            if random.random() < 0.05:
                hub.room_update(pop_rank=random.randint(8, 40), area_rank=random.randint(1, 20), area_rank_name='虚拟Gamer小时榜')
        elif r < 0.78:
            hub.enter(uid, n, '', random.choice(['enter', 'enter', 'enter', 'follow']),
                      3 if n == '路过的舰长' else 0)
        elif r < 0.93:
            g = random.choice([('小花花', 0.1), ('打call', 0.5), ('牛哇牛哇', 0.1), ('这个好诶', 1), ('情书', 52)])
            num = random.randint(1, 5)
            hub.gift(uid, n, '', g[0], num, g[1] * num)
        elif r < 0.98:
            hub.super_chat(i, uid, n, '', random.choice([30, 50, 100]), '主播辛苦啦，今天的歌超好听，早点休息哦～')
        else:
            hub.guard_buy(uid, n, 3, 1, 198, op=random.choice(['开通', '续费']), days=random.randint(1, 500))
        if i % 37 == 0:
            hub.room_block(uid, n, {'operator': 1, 'uid': uid, 'uname': n})
        if i % 20 == 0:
            hub.room_update(watched=hub.state.room['watched'] + random.randint(1, 9),
                            online=max(60, hub.state.room['online'] + random.randint(-4, 5)))
        await asyncio.sleep(random.uniform(0.4, 1.6))


# 礼物动图（2026-11-18）：B 站礼物配置里每个礼物都有会动的 webp / gif。
# 记下「静态图地址 → 动图地址」和「礼物名 → (静态图, 动图)」，新礼物来了网页上播几秒动图
GIFT_ANIM, GIFT_BY_NAME, GIFT_BY_ID = {}, {}, {}  # 同名礼物 B 站有好几个版本（新旧图不同），送礼时按礼物编号找最准
# 官方大特效（2026-11-18）：B 站直播间满屏特效是带透明通道的 mp4（左半彩色、右边小一号的是透明度），
# 配一个 json 说两块各在哪。礼物编号 → (mp4, json)；礼物名 → 最新版的礼物编号（演示模式按名字找）
GIFT_FX, GIFT_NAME_ID = {}, {}
WEALTH_ICON = {}  # 荣耀等级 → B 站官方等级勋章图（1–80 级每级一张，2026-11-19）
GUARD_FX = {}  # 上舰等级 → (mp4, json)：B 站官方上舰特效（恭喜舰长登船 / 提督就任 / 总督上任）
GUARD_FX_CONF = {3: 397, 2: 398, 1: 399}
FX_URL = re.compile(r'https://i[0-2]\.hdslb\.com/bfs/live/[0-9a-f]{40}\.(?:mp4|json)')


def gift_fx(gift_id=0, gift_name=''):
    return GIFT_FX.get(gift_id) or GIFT_FX.get(GIFT_NAME_ID.get(gift_name, -1)) or ('', '')


WEALTH_CACHE = ''  # 荣耀等级图标存一份在 data 里，重启后第一时间就有（演示模式不存）


def load_wealth_cache():
    try:
        with open(WEALTH_CACHE, encoding='utf-8') as f:
            j = json.load(f)
        icons = {int(k): v for k, v in j.items() if str(k).isdigit() and isinstance(v, str) and validation.safe_url(v)}
        if icons and not WEALTH_ICON:
            WEALTH_ICON.update(icons)
    except (OSError, ValueError, TypeError, AttributeError):
        pass


async def watch_gift_anim(session, room_id):
    # 2026-11-25：荣耀等级图标先拿（以前排在礼物列表后面，刚启动那几秒打开的页面只能显示色块）
    if WEALTH_CACHE:
        load_wealth_cache()
    try:
        await fetch_wealth_icons(session)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        log.warning('荣耀等级图标没拿到：%s', e)
    while True:
        try:
            async with session.get('https://api.live.bilibili.com/xlive/web-room/v1/giftPanel/giftConfig',
                                   params={'platform': 'pc', 'room_id': str(room_id or DEMO_ROOM)},
                                   timeout=aiohttp.ClientTimeout(total=20)) as r:
                j = await r.json(content_type=None)
            items = (j.get('data') or {}).get('list') or [] if isinstance(j, dict) else []
            anim, by_name, by_id, name_id, effect_of = {}, {}, {}, {}, {}
            for g in items[:3000]:
                if not isinstance(g, dict):
                    continue
                img = validation.safe_url(str(g.get('img_basic') or ''))
                moving = validation.safe_url(str(g.get('webp') or g.get('gif') or ''))
                if img and moving:
                    anim[img] = moving
                    gid, nm = int(g.get('id') or 0), str(g.get('name') or '')
                    by_id[gid] = (img, moving)
                    effect_of[gid] = int(g.get('effect_id') or 0)
                    if gid >= name_id.get(nm, -1):  # 同名的取编号最大的（最新版的图）
                        name_id[nm] = gid
                        by_name[nm] = (img, moving)
            if anim:
                GIFT_ANIM.clear(); GIFT_ANIM.update(anim)
                GIFT_BY_NAME.clear(); GIFT_BY_NAME.update(by_name)
                GIFT_BY_ID.clear(); GIFT_BY_ID.update(by_id)
                log.info('礼物动图：认得 %d 个', len(anim))
                try:
                    await fetch_wealth_icons(session)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                    log.warning('荣耀等级图标没拿到：%s', e)
                try:
                    fx = await fetch_gift_fx(session, room_id, effect_of)
                    if fx:
                        GIFT_FX.clear(); GIFT_FX.update(fx)
                        GIFT_NAME_ID.clear(); GIFT_NAME_ID.update(name_id)
                        log.info('礼物大特效：认得 %d 个', len(fx))
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                    log.warning('礼物大特效列表没拿到：%s', e)
            await asyncio.sleep(12 * 3600 if anim else 600)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # 拿不到就先不播动图，十分钟后再试
            log.warning('礼物动图列表没拿到：%s', e)
            await asyncio.sleep(600)


async def fetch_wealth_icons(session):
    async with session.get('https://api.live.bilibili.com/xlive/general-interface/v1/content/get', params={'key': 'wealth'},
                           headers={'User-Agent': 'Mozilla/5.0'}, timeout=aiohttp.ClientTimeout(total=20)) as r:
        j = await r.json(content_type=None)
    content = json.loads(((j.get('data') or {}).get('content')) or '{}')
    icons = {}
    for m in content.get('wealth_level_medal') or []:
        if isinstance(m, dict) and isinstance(m.get('id'), int) and 0 < m['id'] < 1000:
            u = validation.safe_url(str(m.get('url') or ''))
            if u:
                icons[m['id']] = u
    if icons:
        WEALTH_ICON.clear(); WEALTH_ICON.update(icons)
        log.info('荣耀等级图标：认得 %d 级', len(icons))
        if WEALTH_CACHE:
            try:
                write_json(WEALTH_CACHE, icons)
            except OSError:
                pass


async def fetch_gift_fx(session, room_id, effect_of):
    async with session.get('https://api.live.bilibili.com/xlive/general-interface/v1/fullScSpecialEffect/GetEffectConfListV2',
                           params={'platform': 'pc', 'room_id': str(room_id or DEMO_ROOM), 'source': 'live', 'build': '0',
                                   'base_version': '0'},
                           headers={'User-Agent': 'Mozilla/5.0'}, timeout=aiohttp.ClientTimeout(total=30)) as r:
        j = await r.json(content_type=None)
    confs = ((j.get('data') or {}).get('full_sc_resource') or {}).get('conf_list') or [] if isinstance(j, dict) else []
    by_conf, by_gift = {}, {}
    for c in confs[:10000]:
        if not isinstance(c, dict):
            continue
        mp4, js = str(c.get('web_mp4') or ''), str(c.get('web_mp4_json') or '')
        if not (FX_URL.fullmatch(mp4) and FX_URL.fullmatch(js)):
            continue
        by_conf[int(c.get('id') or 0)] = (mp4, js)
        for gid in c.get('bind_gift_ids') or []:
            if isinstance(gid, int) and gid > 0:
                by_gift.setdefault(gid, (mp4, js))
    GUARD_FX.clear()
    GUARD_FX.update({lv: by_conf[cid] for lv, cid in GUARD_FX_CONF.items() if cid in by_conf})
    out = {}
    for gid, eid in effect_of.items():  # 礼物自己写的特效编号优先，没有再看特效绑了哪些礼物
        fx = by_conf.get(eid) or by_gift.get(gid)
        if fx:
            out[gid] = fx
    return out


def demo_history(history):
    """演示模式：没有历史时造几场假的，看历史页面的样子。"""
    if history.list():
        return
    titles = ['【歌回】今天唱点冬天的歌', '杂谈～陪大家聊聊天', '【歌回】点歌环节', '一起看雪', '周末歌回']
    now = time.time()
    for d, title in enumerate(titles, 1):
        st = State(0)
        st.file = None
        st.was_live = True
        st.live_start = int(now - d * 86400 - random.randint(0, 3) * 3600)
        st.session_start = st.live_start
        st.meta = {'title': title, 'area': '唱见电台'}
        st.stats = {'peak_online': random.randint(80, 200), 'follows': random.randint(5, 40),
                    'watched': random.randint(2000, 6000), 'likes': random.randint(2000, 9000)}
        for _ in range(random.randint(30, 80)):
            n = random.choice(DEMO_NAMES)
            uid = DEMO_NAMES.index(n) + 1000
            st.touch_user(uid, n, dm=random.randint(1, 30))
            k = random.random()
            if k < 0.3:
                g, p = random.choice([('小花花', 0.1), ('打call', 0.5), ('这个好诶', 1), ('情书', 52)])
                num = random.randint(1, 5)
                gs = st.gift_stats.setdefault(g, {'num': 0, 'yuan': 0.0})
                gs['num'] += num
                gs['yuan'] = round(gs['yuan'] + p * num, 2)
                st.flow['gift'] = round(st.flow['gift'] + p * num, 2)
                st.touch_user(uid, n, spend=p * num)
            elif k < 0.38:
                price = random.choice([30, 50, 100])
                st.scs.append({'id': len(st.scs) + 1, 't': st.live_start + random.randint(60, 7000), 'uid': uid,
                               'name': n, 'face': '', 'price': price, 'guard': 0,
                               'text': random.choice(['主播辛苦啦～', '今天的歌超好听', '晚安，早点休息哦'])})
                st.flow['sc'] += price
                st.touch_user(uid, n, spend=price)
            elif k < 0.41:
                st.guards.append({'t': st.live_start + random.randint(60, 7000), 'uid': uid, 'name': n, 'level': 3,
                                  'level_name': '舰长', 'num': 1, 'unit': '月', 'yuan': 198})
                st.flow['guard'] += 198
                st.touch_user(uid, n, spend=198, guard=3)
        history.save(st.summary('下播', st.live_start + random.randint(5400, 10800)))


def is_admin(request, admin_key, port):
    """在电脑上直接打开的（不是从 Cloudflare 隧道进来的），或者带了管理密钥的，才能清零、删历史。"""
    k = request.query.get('admin', '') or request.cookies.get('xwadmin', '')
    if isinstance(admin_key, AdminLinks):
        if admin_key.authenticate(k):
            return True
    elif admin_key and hmac.compare_digest(k.encode('utf-8'), admin_key.encode('utf-8')):
        return True
    tunneled = 'CF-Connecting-IP' in request.headers or 'Cf-Ray' in request.headers
    local_hosts = {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}
    origin = request.headers.get('Origin', '')
    return (not tunneled and request.remote in ('127.0.0.1', '::1')
            and request.host.lower() in local_hosts
            and (not origin or origin.lower() == 'http://' + request.host.lower()))


async def collect_side_rooms(side_hubs):
    while True:
        await asyncio.sleep(60)
        # 2026-11-21 补漏洞：短房号和真房号指向同一套，每轮只数一次（以前会数两次，提前一轮关掉）
        for e in list({id(v): v for v in side_hubs.values()}.values()):
            if e['hub'].sockets:
                e['idle'] = 0
                continue
            e['idle'] += 1
            if e['idle'] >= 2:
                for k in [k for k, v in side_hubs.items() if v is e]:
                    side_hubs.pop(k, None)
                e['task'].cancel()
                try:
                    if e.get('client'):  # 别的平台没有 B 站连接，只有上面那个任务（2026-11-26）
                        await e['client'].stop_and_close()
                except Exception as ex:
                    log.warning('关别的直播间连接出错：%s', ex)
                log.info('别的直播间 %s 没人看了，已关掉', e['hub'].side_info.get('room'))


async def send_own_danmaku(bare, state, room_id, own_at, acct, text, reply_uid=0, reply_dmid=''):
    text = text.strip()
    if not text or len(text) > 40:
        return False, '写一句话，最多 40 个字'
    uid = acct.get('uid')
    if time.time() - own_at.get(uid, 0) < 3:
        return False, '发太快了，隔 3 秒再发'
    m = re.search(r'bili_jct=([^;]+)', acct.get('cookie', ''))
    if not m:
        return False, '这个号的登录信息不完整，退出后重新扫码登录'
    own_at[uid] = time.time()
    room = state.room.get('room_real') or room_id
    data = {'bubble': '0', 'msg': text, 'color': '16777215', 'mode': '1', 'room_type': '0', 'jumpfrom': '0',
            'reply_mid': str(int(reply_uid or 0)), 'reply_attr': '0', 'replay_dmid': str(reply_dmid or ''), 'statistics': '{"appId":100,"platform":5}',
            'fontsize': '25', 'rnd': str(int(time.time())), 'roomid': str(room), 'csrf': m.group(1), 'csrf_token': m.group(1)}

    async def post(form):
        async with bare.post('https://api.live.bilibili.com/msg/send', data=form,
                             headers={'Cookie': acct['cookie'], 'Origin': 'https://live.bilibili.com',
                                      'Referer': f'https://live.bilibili.com/{room}'},
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
            return await r.json(content_type=None)
    fallback = ''
    try:
        j = await post(data)
        # 回复没被 B 站接受（不是登录问题）：去掉回复，按普通弹幕再发一次，免得这句话发不出去
        if reply_uid and j.get('code') not in (0, -101):
            log.warning('回复弹幕没成功（%s %s），按普通弹幕重发', j.get('code'), j.get('message') or j.get('msg'))
            data.update(reply_mid='0', replay_dmid='')
            j = await post(data)
            fallback = '（回复没成功，按普通弹幕发出了）'
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return False, '连不上 B 站，稍后再试'
    if j.get('code') != 0:
        if j.get('code') == -101:
            return False, '这个号的登录过期了，退出后重新扫码登录'
        return False, f"B 站没让发（{j.get('code')} {j.get('message') or j.get('msg') or ''}）"
    log.info('%s 用自己的号从雾幕发了弹幕：%s%s', acct.get('uname'), text, '（回复）' if reply_uid and not fallback else '')
    msg = j.get('message') or j.get('msg')
    return True, (f'已发出，但 B 站提示「{msg}」（可能被屏蔽词拦了）' if msg else f"已用 {acct.get('uname')} 的号{'回复' if reply_uid and not fallback else '发出'}") + fallback


async def get_room_news(bare, state, room_id):
    room, ruid = state.room.get('room_real') or room_id, state.room.get('uid')
    if not ruid:
        return False, '还没拿到直播间信息，稍后再试', {}
    try:
        async with bare.get('https://api.live.bilibili.com/room_ex/v1/RoomNews/get', params={'roomid': str(room), 'uid': str(ruid)},
                            headers={'Referer': f'https://live.bilibili.com/{room}'}, timeout=aiohttp.ClientTimeout(total=15)) as r:
            j = await r.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return False, '连不上 B 站，稍后再试', {}
    if j.get('code') != 0:
        return False, f"没读到公告（{j.get('code')} {j.get('message') or ''}）", {}
    d = j.get('data') if isinstance(j.get('data'), dict) else {}
    return True, '', {'text': str(d.get('content') or '')[:200], 'ctime': str(d.get('ctime') or '')[:20]}


async def set_room_news(bare, state, room_id, acct, text):
    if not acct or acct.get('uid') != state.room.get('uid'):
        return False, '要主播本人的号才能改公告（先在发送框左边扫码登录主播的号）'
    m = re.search(r'bili_jct=([^;]+)', acct.get('cookie', ''))
    if not m:
        return False, '登录信息不完整，重新扫码'
    text = str(text or '').strip()
    if len(text) > 60:
        return False, '公告最多 60 个字'
    room = state.room.get('room_real') or room_id
    headers = {'Cookie': acct['cookie'], 'Origin': 'https://link.bilibili.com', 'Referer': 'https://link.bilibili.com/p/center/index'}
    tries = [('https://api.live.bilibili.com/xlive/app-blink/v1/index/updateRoomNews', {'room_id': str(room), 'uid': str(acct['uid'])}),
             ('https://api.live.bilibili.com/room_ex/v1/RoomNews/update', {'roomid': str(room), 'uid': str(acct['uid'])})]
    j = {}
    for url, base in tries:
        try:
            async with bare.post(url, data={**base, 'content': text, 'csrf': m.group(1), 'csrf_token': m.group(1)}, headers=headers,
                                 timeout=aiohttp.ClientTimeout(total=15)) as r:
                j = await r.json(content_type=None) if r.status == 200 else {'code': -r.status}
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return False, '连不上 B 站，稍后再试'
        if j.get('code') == 0:
            log.info('%s 从雾幕改了直播间公告：%s', acct.get('uname'), text)
            # 2026-11-21 实测：B 站回「OK」，但 2 分钟内读到的还是旧公告（可能要审核）。读一次，照实说
            ok, _, got = await get_room_news(bare, state, room_id)
            if ok and got.get('text') == text:
                return True, '公告改好了'
            return True, 'B 站收下了，但现在显示的还是旧公告，可能要审核，过一会儿再看看'
        if j.get('code') == -101:
            return False, '这个号的登录过期了，重新扫码'
        if j.get('code') not in (-404, -400, 404):
            break  # B 站回了别的原因，不再换接口试
    return False, f"B 站没同意（{j.get('code')} {j.get('message') or j.get('msg') or ''}）"


def complete_guard_days(hub, items):
    """旧的上舰记录没有「陪伴第几天」（2026-11-20 之前没记）：用 B 站舰长名单里现在的陪伴天数往回推，标 days_est。
    只补现在还在船上的人；推出来不是正数就不补。返回有没有补到。"""
    now_days = {r.get('uid'): r.get('days') for r in hub.guardlist if isinstance(r.get('days'), int) and r.get('days') > 0}
    if not now_days:
        return False
    day = lambda t: int((t + 8 * 3600) // 86400)  # 北京时间的第几天
    today, changed = day(time.time()), False
    for g in items:
        if isinstance(g, dict) and not g.get('days') and g.get('uid') in now_days:
            d = now_days[g['uid']] - (today - day(g.get('t', 0)))
            if 0 < d < 100000:
                g['days'], g['days_est'], changed = d, True, True
    return changed


async def list_offline(request, state, hub, links, port):
    """下播期间收到的礼物、SC、上舰（2026-11-20 用户要在历史记录里看）：data/offline 里每段下播一个文件，加上现在还没存的。"""
    if not is_admin(request, links, port):
        raise web.HTTPForbidden()
    s = state
    out, seen = {'gifts': [], 'scs': [], 'guards': []}, set()
    off_dir = os.path.join(DIR, 'data', 'offline', str(s.room_id))
    try:
        names = sorted(os.listdir(off_dir))
    except OSError:
        names = []
    sources = []
    for n in names:
        try:
            with open(os.path.join(off_dir, n), encoding='utf-8') as f:
                off = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(off, dict):  # 2026-11-21 补漏洞：文件里不是正常的一段记录（比如被写成了列表）就跳过
            sources.append(off)
    since = s.settled_at if s.summarized else 0
    # 2026-11-21 修：本场还留着的那份放最前面——同一条两边都有时，以本场那份（最新的已感谢状态）为准
    sources.insert(0, {k: [x for x in getattr(s, k) if x.get('source') == '下播' or (s.summarized and x.get('t', 0) > since)]
                       for k in ('gifts', 'scs', 'guards')})
    for src in sources:
        for k in out:
            for x in src.get(k) or []:
                if not isinstance(x, dict):
                    continue
                key = (k, x.get('id') or (x.get('uid'), x.get('t')))
                if key in seen:
                    if x.get('thanked'):  # 哪一份标过已感谢都算（旧数据两份可能不一样）
                        for y in out[k]:
                            if (k, y.get('id') or (y.get('uid'), y.get('t'))) == key:
                                y['thanked'] = True
                    continue
                seen.add(key)
                out[k].append(dict(x, source='下播'))
    for k in out:
        out[k].sort(key=lambda x: -x.get('t', 0))
    complete_guard_days(hub, out['guards'])
    for g in out['gifts']:
        if not g.get('img'):
            g['img'] = (GIFT_BY_NAME.get(g.get('gift')) or ('', ''))[0]
    flow = {'gift': round(sum(x.get('yuan') or 0 for x in out['gifts']), 2), 'sc': round(sum(x.get('price') or 0 for x in out['scs']), 2),
            'guard': round(sum(x.get('yuan') or 0 for x in out['guards']), 2)}
    return web.json_response({**out, 'flow': flow, 'total': round(sum(flow.values()), 2)}, headers={'Cache-Control': 'no-store'})


def apply_pack_config(cfg):
    """config.json 里包、品牌和几个可选项（2026-11-26）"""
    global PACK, BRAND, HOST_PATH, GEQU_DIR, DISCORD_WEBHOOK_FILE, LOGIN_READONLY, ALERT_PORT, MANAGED_RESTART
    def here(p):
        p = str(p or '')
        return p if not p or os.path.isabs(p) else os.path.join(DIR, p)
    PACK = here(cfg.get('pack'))
    if PACK and not os.path.isdir(PACK):
        raise SystemExit(f'config.json 的 pack 文件夹不存在：{PACK}')
    b = cfg.get('brand') if isinstance(cfg.get('brand'), dict) else {}
    BRAND = {'name': str(b.get('name') or '雾幕')[:20], 'short': str(b.get('short') or '主播')[:12], 'medal': str(b.get('medal') or '粉丝团')[:8]}
    hp = str(cfg.get('host_path') or '/host')
    if not re.fullmatch(r'/[a-z0-9-]{1,30}', hp) or hp in ('/obs', '/ws', '/img', '/static', '/api', '/art'):
        raise SystemExit('config.json 的 host_path 只能是 / 开头的小写字母、数字、横线')
    HOST_PATH = hp
    GEQU_DIR = here(cfg.get('gequ_dir'))
    DISCORD_WEBHOOK_FILE = here(cfg.get('discord_webhook_file'))
    LOGIN_READONLY = cfg.get('login_readonly') is True
    ALERT_PORT = int(cfg.get('alert_port') or 0)
    MANAGED_RESTART = cfg.get('managed_restart') is True


SECRET_WORDS = ('webhook', 'key', 'cookie', 'token', 'password', 'secret', 'sessdata')


def redact(obj):
    """诊断信息里藏掉密钥一类的东西"""
    if isinstance(obj, dict):
        return {k: ('***' if any(w in str(k).lower() for w in SECRET_WORDS) and obj[k] else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def mask_line(line):
    """日志里的 IP 打码、像 cookie 的长串去掉"""
    line = re.sub(r'\b(\d{1,3})\.\d{1,3}\.\d{1,3}\.(\d{1,3})\b', r'\1.*.*.\2', line)
    return re.sub(r'(SESSDATA|bili_jct|MUSIC_U|DedeUserID)=[^;\s]+', r'\1=***', line)


def load_config(path):
    """config.json（可选）：命令行没写的就用这里的值，见 config.example.json。"""
    try:
        with open(path, encoding='utf-8-sig') as f:
            cfg = json.load(f)
    except FileNotFoundError:
        return {}
    if not isinstance(cfg, dict):
        raise SystemExit(f'{path} 格式不对：应该是一个 JSON 对象')
    return cfg


async def main():
    global LOGIN_FILE, DISCORD_WEBHOOK, BOT_SAY_URL, WEALTH_CACHE
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument('--config', default=os.path.join(DIR, 'config.json'))
    cfg = load_config(pre.parse_known_args()[0].config)
    ap = argparse.ArgumentParser(parents=[pre])
    ap.add_argument('--room', type=int, default=int(cfg.get('room') or 0), help='直播间号（必填，或者写在 config.json）')
    ap.add_argument('--anchor-name', default=str(cfg.get('anchor_name') or ''), help='主播名字，显示在切换直播间菜单里')
    ap.add_argument('--port', type=int, default=int(cfg.get('port') or 8373))
    cfg_lan = cfg.get('lan') is True
    ap.add_argument('--host', default=str(cfg.get('host') or '127.0.0.1'))
    ap.add_argument('--login-file', default=str(cfg.get('login_file') or LOGIN_FILE), help='B 站登录信息文件（{"cookie": "..."}）')
    ap.add_argument('--discord-webhook', default=str(cfg.get('discord_webhook') or ''), help='掉线提醒发到这个 Discord webhook')
    ap.add_argument('--bot-say-url', default=str(cfg.get('bot_say_url') or ''), help='可选：代发弹幕的本地接口')
    ap.add_argument('--demo', action='store_true')
    ap.add_argument('--key', default='', help='不想公开时用：打开网页要带 ?key=这个值')
    ap.add_argument('--admin-key', default='', help='公开时，带 ?admin=这个值 打开的人也能清零本场、删历史（电脑上本来就能）')
    ap.add_argument('--log', default='', help='日志写到这个文件（自动轮换，不会越写越大）')
    ap.add_argument('--public-url', default=str(cfg.get('public_url') or ''), help='外网地址（可选）：掉线提醒用它检查隧道通不通')
    ap.add_argument('--error-hour', type=int, choices=range(24), default=10, help='错误汇总发送时间（本机时间，整点）')
    ap.add_argument('--health-hour', type=int, choices=range(24), default=9, help='每日体检时间（本机整点）')
    for name, default in (('public-max', 200), ('public-ip-max', 20), ('public-connect-rate', 60),  # 审查时调大：手机流量常常很多人共用一个出口 IP，5 条太容易误伤
                          ('public-http-rate', 600), ('gequ-http-rate', 3000), ('obs-max', 50), ('obs-ip-max', 10)):
        ap.add_argument('--' + name, type=int, default=default)
    ap.add_argument('--no-alert', action='store_true', help='不发掉线提醒（测试直播间用）')
    ap.add_argument('--no-update-check', action='store_true', default=cfg.get('update_check') is False,
                    help='不去 GitHub 查有没有新版本（也可以在 config.json 写 "update_check": false）')
    ap.add_argument('--update-url', default='', help=argparse.SUPPRESS)  # 测试用：换一个地址模拟「有新版本」
    ap.add_argument('--version', action='version', version=f'bili-danmaku-board {updates.VERSION}')
    args = ap.parse_args()
    if not args.demo and not args.room:
        ap.error('要告诉我连哪个直播间：加 --room 房间号，或者在 config.json 里写 "room"')
    LOGIN_FILE, DISCORD_WEBHOOK, BOT_SAY_URL = args.login_file, args.discord_webhook, args.bot_say_url
    apply_pack_config(cfg)
    restored = apply_pending_restore() if not args.demo else None  # 页面上点了「从这份恢复」：先换好 data 再往下读
    if not os.path.isabs(LOGIN_FILE):
        LOGIN_FILE = os.path.join(DIR, LOGIN_FILE)
    for name in ('public_max', 'public_ip_max', 'public_connect_rate', 'public_http_rate', 'gequ_http_rate', 'obs_max', 'obs_ip_max'):
        if not 1 <= getattr(args, name) <= 100000:
            ap.error(name + ' 必须为 1–100000')
    handlers = [logging.StreamHandler()]
    if args.log:
        handlers = [logging.handlers.RotatingFileHandler(os.path.join(DIR, args.log), maxBytes=1 << 20,
                                                         backupCount=2, encoding='utf-8')]
    for handler in handlers:
        handler.setFormatter(AdminSafeFormatter('%(asctime)s %(message)s'))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', handlers=handlers)
    journal = ErrorJournal(os.path.join(DIR, 'data', 'errors.json') if not args.demo else None,
                           os.path.join(DIR, 'data', 'error-report.json') if not args.demo else None, write_json, args.error_hour)
    restore_errors = journal.install(asyncio.get_running_loop())
    for handler in logging.getLogger().handlers:
        if handler is not journal:
            handler.addFilter(connection_recovery.RepeatFilter())
    if not args.admin_key and not args.demo:
        # 管理链接的密码放在 admin.key 里（网址后面加 ?admin=这串字），删掉这个文件就没有管理链接了
        try:
            with open(os.path.join(DIR, 'admin.key'), encoding='utf-8') as f:
                args.admin_key = f.read().strip()
        except OSError:
            pass

    links = AdminLinks(os.path.join(DIR, 'data', 'admin-links.json') if not args.demo else None, write_json, args.admin_key)
    new_release = [None]  # GitHub 上查到的新版本（updates.watch 填）
    health = DailyHealth(DIR, write_json, persist=not args.demo, hour=args.health_hour)
    limits = PublicLimits(args.public_max, args.public_ip_max, args.public_connect_rate, args.public_http_rate,
                          args.gequ_http_rate, args.obs_max, args.obs_ip_max)

    # 没处理的消息类型 blivedm 每种会打一条很长的日志，太吵，不要
    logging.getLogger('blivedm').addFilter(lambda r: 'unknown cmd' not in str(r.msg))

    room_id = 0 if args.demo else args.room
    state = State(room_id)
    state.room['anchor_name'] = args.anchor_name or '主播'
    history = History(room_id)
    accounts = Accounts()
    if args.demo:
        state.file = None  # 演示数据不存
        state.reset()
        demo_history(history)
    IMG_CACHE_READY = clean_img_cache()
    hub = Hub(state, history, persist=not args.demo)
    hub.music = MusicService(os.path.join(DIR, 'data'), not args.demo, write_json, log, hub.emit, hub.emit_admin)
    hub.platforms = Platforms(hub, os.path.join(DIR, 'data'), not args.demo, write_json, log, lambda: bare)
    hub.admin_links, hub.public_limits = links, limits
    if args.demo:
        now = int(time.time())
        hub.guardlist = [{'uid': 1000 + i, 'name': n, 'face': '', 'level': 3 if i else 2, 'days': 30 + i * 41,
                          'until': now + (3 + i * 9) * 86400, 'est': bool(i % 2)} for i, n in enumerate(DEMO_NAMES[:5])]
        hub.notes.data = {'1003': {'note': '老观众，喜欢点周杰伦', 'name': '小鱼干', 't': now}}

    def page(name):
        # workbench.js / .css、app/ 下各文件的 ?v= 自动换成它们的改动时间：改了文件，浏览器和 Cloudflare 都会拿新的，不会再用旧缓存报错。
        # 2026-11-21 用户：OBS 设置也对普通链接放开（只是拼一个网址，OBS 页面本来就是公开的；发测试弹幕之类的操作后台照样只认管理身份）
        # no-cache：不让浏览器用旧版（2026-11-19：雾蓝预览一直是旧页面，没有唱片封面）
        async def handler(request):
            return web.Response(text=render_page(name), content_type='text/html', headers={'Cache-Control': 'no-cache'})
        return handler

    index = page('index')
    obs_setup = page('obs-setup')

    async def static_file(request):
        """static/ 下的文件；包里有同名的用包里的（2026-11-26）"""
        rel = request.match_info.get('path', '')
        parts = rel.replace('\\', '/').split('/')
        if not rel or any(p in ('', '.', '..') or ':' in p for p in parts):
            raise web.HTTPNotFound()
        path = static_path('/'.join(parts))
        if not os.path.isfile(path):
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    def open_where(request):
        """这次打开是从哪来的（2026-11-19）：IP 和地区都来自 Cloudflare 加的请求头；城市要在 Cloudflare 开「访客位置请求头」才有。"""
        h = request.headers
        ua = h.get('User-Agent', '')
        browser = next((n for k, n in (('Edg/', 'Edge'), ('OPR/', 'Opera'), ('Firefox/', 'Firefox'), ('Chrome/', 'Chrome'), ('Safari/', 'Safari')) if k in ua), '')
        system = next((n for k, n in (('iPhone', 'iPhone'), ('iPad', 'iPad'), ('Android', 'Android'), ('Windows', 'Windows'), ('Mac OS', 'Mac'), ('Linux', 'Linux')) if k in ua), '')
        local = 'CF-Connecting-IP' not in h
        return {'ip': '本机' if local else h.get('CF-Connecting-IP', ''), 'cc': '' if local else h.get('CF-IPCountry', ''),
                'region': h.get('cf-region', ''), 'city': h.get('cf-ipcity', ''), 'dev': ' · '.join(x for x in (system, browser) if x)}

    # 切到别的直播间（2026-11-20）：每个房间一套 SideHub，有页面在看就开着，没人看两分钟后关掉
    side_hubs = {}

    async def side_hub(room):
        e = side_hubs.get(room)
        if e:
            e['idle'] = 0
            return e['hub']
        async with session.get(f'https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room}', timeout=aiohttp.ClientTimeout(total=10)) as r:
            d = (await r.json(content_type=None)).get('data') or {}
        if not d.get('uid'):
            raise ValueError('找不到这个直播间')
        real = d.get('room_id') or room
        if real in (args.room, state.room.get('room_real')):
            return hub
        e = side_hubs.get(real)
        if e:
            side_hubs[room] = e
            e['idle'] = 0
            return e['hub']
        uname = ''
        try:
            async with session.get(f"https://api.live.bilibili.com/live_user/v1/Master/info?uid={d['uid']}", timeout=aiohttp.ClientTimeout(total=10)) as r:
                uname = str((((await r.json(content_type=None)).get('data') or {}).get('info') or {}).get('uname') or '')[:40]
        except Exception:
            pass
        h = SideHub(MemState(real), NullHistory(), persist=False)
        h.admin_links, h.public_limits, h.bot_uids = hub.admin_links, hub.public_limits, state.bot_uids
        h.state.bot_uids = state.bot_uids
        h.side_info = {'room': real, 'uname': uname, 'uid': d['uid']}
        client = blivedm.BLiveClient(real, session=session)
        client.set_handler(Handler(h))
        client.start()
        h.client = client
        await side_backfill(h, real)
        e = {'hub': h, 'client': client, 'task': asyncio.create_task(poll_room(h, session, real)), 'idle': 0}
        side_hubs[room] = side_hubs[real] = e
        if not side_gc_task:
            side_gc_task.append(asyncio.create_task(side_gc()))
        log.info('切到别的直播间 %s（%s）', real, uname)
        return h

    side_gc_task = []

    async def side_hub_plat(plat, room):
        """切到斗鱼 / 虎牙 / 抖音的直播间（2026-11-26）：跟「其他平台」一样的连接，只是收进一套单独的 SideHub 里"""
        key = f'{plat}:{room}'
        e = side_hubs.get(key)
        if e:
            e['idle'] = 0
            return e['hub']
        if plat == 'douyin' and not hub.platforms.view().get('douyin'):
            raise ValueError('抖音要在装了 Edge / Chrome 的 Windows 电脑上开')
        row = next((r for r in hub.xrooms['rooms'] if xroom_key(r) == key), None)
        label = platforms.PLATS[plat][0]
        h = SideHub(MemState(int(room) % 10**12), NullHistory(), persist=False)
        h.admin_links, h.public_limits, h.bot_uids = hub.admin_links, hub.public_limits, []
        h.side_info = {'room': key, 'uname': (row or {}).get('name') or f'{label} {room}', 'plat': plat}
        h.state.room['live'] = 1  # 别的平台不查开没开播，先当在播
        src = platforms.CLASSES[plat](h, plat, str(room), log)
        e = {'hub': h, 'client': None, 'src': src, 'task': asyncio.create_task(src.run(bare)), 'idle': 0}
        side_hubs[key] = e
        if not side_gc_task:
            side_gc_task.append(asyncio.create_task(side_gc()))
        log.info('切到%s直播间 %s', label, room)
        return h

    async def fill_xroom_names():
        """切房名单里没名字的（刚加进去的），去 B 站查用户名填上（2026-11-21）。"""
        rooms, changed = [dict(r) for r in hub.xrooms['rooms']], False
        for r in rooms:
            if r.get('name') or r.get('plat'):  # 别的平台的名字自己填（查不到用户名）
                continue
            try:
                async with session.get(f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={r['room']}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    uid = ((await resp.json(content_type=None)).get('data') or {}).get('uid')
                if not uid:
                    continue
                async with session.get(f"https://api.live.bilibili.com/live_user/v1/Master/info?uid={uid}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    uname = str((((await resp.json(content_type=None)).get('data') or {}).get('info') or {}).get('uname') or '').strip()[:40]
                if uname:
                    r['name'], changed = uname, True
            except Exception as e:
                log.info('查直播间 %s 的用户名失败：%s', r['room'], e)
        if changed:
            hub.xrooms_set({'open': hub.xrooms['open'], 'rooms': rooms})

    async def kick_side_viewers():
        """名单改了 / 开关关了：还在看别的直播间、但现在不让看的普通链接断开，它们自己重连就回到主播这边。"""
        for e in list({id(e): e for e in side_hubs.values()}.values()):
            h = e['hub']
            if hub.xroom_allowed(h.side_info.get('room')):
                continue
            for ws in list(h.viewers):
                h.drop_socket(ws)
                try:
                    await asyncio.wait_for(ws.close(code=4003, message='这个直播间现在不能看了'.encode()), 2)
                except (asyncio.TimeoutError, ConnectionError):
                    pass

    async def side_backfill(h, room):
        return await backfill_side_room(session, h, room)

    async def side_gc():
        return await collect_side_rooms(side_hubs)

    # 手机打开（2026-11-25）：默认只听本机 127.0.0.1，手机打不开；在设置 → 链接里打开后，同一个 Wi-Fi 的手机
    # 用「http://电脑的局域网地址:端口」就能打开（还是要管理链接才有管理身份）。开关记在 config.json 的 "lan"
    lan = {'on': False, 'ip': '', 'site': None}

    def lan_ip():
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))  # 不会真的发包，只是让系统选一块网卡
            ip = s.getsockname()[0]
        except OSError:
            ip = ''
        finally:
            s.close()
        return ip if ip and not ip.startswith('127.') else ''

    def lan_url():
        return f'http://{lan["ip"]}:{args.port}' if lan['on'] and lan['ip'] else ''

    def origin_ok(request):
        if trusted_origin(request.headers.get('Origin', ''), request.host, args.public_url, args.port):
            return True
        return bool(lan_url()) and trusted_origin(request.headers.get('Origin', ''), request.host, lan_url(), args.port)

    async def lan_set(on, save=True):
        if on and not lan['site']:
            ip = lan_ip()
            if not ip:
                return False, '没找到这台电脑的局域网地址，连上 Wi-Fi 或网线再试'
            if args.host in ('0.0.0.0', '::', ip):
                lan.update(on=True, ip=ip)
            else:
                try:
                    site = web.TCPSite(runner, ip, args.port)
                    await site.start()
                except OSError as e:
                    return False, f'打不开局域网端口：{e}'
                lan.update(on=True, ip=ip, site=site)
        elif not on:
            if lan['site']:
                try:
                    await lan['site'].stop()
                except Exception:  # 关不掉也只是还能连上，不影响本机
                    pass
            lan.update(on=False, site=None)
        if save and not args.demo:
            try:
                conf = load_config(args.config)
                conf['lan'] = bool(on)
                write_json(args.config, conf)
            except (OSError, SystemExit, ValueError):
                pass
        log.info('手机打开（局域网）：%s', lan_url() or '关')
        return True, ('手机连同一个 Wi-Fi，打开 ' + lan_url()) if on else '已关掉，手机打不开了'

    # ---------- 桌面版：软件内更新、打开方式、桌面快捷方式（2026-11-25） ----------
    launcher = os.environ.get('BDB_LAUNCHER') == '1'
    upd_busy = [False]

    def desktop_info():
        v, _ = updates.staged(DIR)
        return {'launcher': launcher, 'open': load_config(args.config).get('open', 'web') if not args.demo else 'web',
                'staged': v or '', 'win': sys.platform == 'win32'}

    async def desktop_cmd(c):
        cmd = c['cmd']
        if cmd == 'update_download':
            info = new_release[0] or await updates.fetch_latest(bare)
            if not info or not updates.is_newer(info['v']):
                return False, '现在已经是最新版'
            if upd_busy[0]:
                return False, '正在下载了'
            upd_busy[0] = True
            last = [-1]

            def prog(p):
                if p - last[0] >= 5 or p == 100:
                    last[0] = p
                    hub.emit_admin('update_progress', {'v': info['v'], 'pct': p})
            try:
                v = await updates.download(bare, info, DIR, prog)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
                hub.emit_admin('update_progress', {'v': info['v'], 'pct': -1})
                return False, f'更新没下载成功：{e}'
            finally:
                upd_busy[0] = False
            hub.emit_admin('desktop', desktop_info())
            try:  # 换新版之前先备份一份 data（2026-11-26）
                await asyncio.get_event_loop().run_in_executor(None, lambda: backup_data(tag='更新前'))
            except OSError as e:
                log.warning('更新前备份没成功：%s', e)
            return True, f'v{v} 下载好了，点「重启生效」换上'
        if cmd == 'update_restart':
            v, _ = updates.staged(DIR)
            if not v:
                return False, '还没下载新版本'
            if not launcher:
                return False, '这次不是用桌面版或 start.bat 打开的，没法自己重启：关掉雾幕再打开就会换上'
            hub.state.dirty = True
            hub.state.save()
            hub.dmlog.flush()
            log.info('点了「重启生效」，换成 v%s', v)
            asyncio.get_event_loop().call_later(1.0, lambda: os._exit(updates.RESTART_CODE))
            return True, f'正在重启换成 v{v}，几秒后页面自己连回来'
        if cmd == 'open_mode':
            mode = 'web' if c.get('mode') == 'web' else 'app'
            if args.demo:
                return False, '演示模式不改设置'
            try:
                conf = load_config(args.config)
                conf['open'] = mode
                write_json(args.config, conf)
            except (OSError, SystemExit, ValueError) as e:
                return False, f'没存上：{e}'
            hub.emit_admin('desktop', desktop_info())
            return True, '下次打开用软件窗口' if mode == 'app' else '下次打开用浏览器'
        if cmd == 'make_shortcut':
            if sys.platform != 'win32':
                return False, '只有 Windows 能建快捷方式'
            exe = sys.executable
            proc = await asyncio.create_subprocess_exec(exe, os.path.join(DIR, 'desktop.py'), '--shortcut', cwd=DIR)
            await proc.wait()
            return proc.returncode == 0, '桌面上建好了「雾幕」' if proc.returncode == 0 else '快捷方式没建成'
        return False, '不支持'

    async def launcher_quit(request):
        """桌面版窗口关掉时，启动器叫服务先存好再退（只认本机 + 启动器给的口令）"""
        t = os.environ.get('BDB_TOKEN', '')
        if not t or request.remote not in ('127.0.0.1', '::1') or not hmac.compare_digest(request.query.get('t', ''), t):
            raise web.HTTPForbidden()
        hub.state.dirty = True
        hub.state.save()
        hub.dmlog.flush()
        log.info('桌面版窗口关了，雾幕退出')
        asyncio.get_event_loop().call_later(0.3, lambda: os._exit(0))
        return web.json_response({'ok': True})

    def qr_svg(text):
        import io
        import qrcode
        import qrcode.image.svg
        buf = io.BytesIO()
        qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2).save(buf)
        return buf.getvalue().decode('utf-8')

    async def ws_handler(request):
        if not origin_ok(request):
            raise web.HTTPForbidden(text='浏览器来源不受信任，请从直播姬页面打开')
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=WS_IMPORT_LIMIT + 1, compress=False)
        client_kind = request.query.get('client', '')
        identity = is_admin(request, links, args.port)
        local = is_admin(request, '', args.port)
        token = request.query.get('admin', '') or request.cookies.get('xwadmin', '')
        link_id = None if local else links.authenticate(token)
        admin = identity and client_kind not in ('obs', 'obs-songs', 'obs-music') and request.query.get('view') != 'public'
        viewer = not admin and client_kind not in ('obs', 'obs-songs', 'obs-music')
        reason = limits.reserve(ws, client_ip(request, args.public_url),
                                'obs' if client_kind in ('obs', 'obs-songs', 'obs-music') else 'public', exempt=identity)
        if reason:
            # 浏览器 WebSocket API 读不到握手失败正文；用拒绝结果和关闭原因让页面能显示。
            await ws.prepare(request)
            await ws.send_json({'type': 'result', 'data': {'cmd': 'connect', 'ok': False, 'msg': reason}})
            await ws.close(code=4008, message=reason.encode('utf-8'))
            return ws
        h = hub
        try:
            await ws.prepare(request)
            if link_id and not links.active(link_id):
                return ws
            want = str(request.query.get('room', ''))
            pm = re.fullmatch(r'(douyu|huya|douyin):(\d{1,20})', want)
            if pm:
                # 别的平台的直播间（2026-11-26）：规矩跟 B 站的一样，管理身份随便看，普通链接 / OBS 要在名单里
                if admin or (viewer and hub.xroom_allowed(want)) or (client_kind == 'obs' and hub.xroom_listed(want)):
                    try:
                        h = await side_hub_plat(pm.group(1), int(pm.group(2)))
                    except Exception as e:
                        await ws.send_json({'type': 'result', 'data': {'cmd': 'connect', 'ok': False, 'msg': f'切换直播间失败：{e}'}})
                elif viewer:
                    await ws.send_json({'type': 'result', 'data': {'cmd': 'connect', 'ok': False, 'msg': f'这个直播间现在不能切过去，先看{BRAND["short"]}这边'}})
            elif want.isdigit() and 0 < int(want) < 10**12 and int(want) != args.room:
                # 普通链接只能切到名单里的，而且开关要开着（2026-11-21）；OBS 弹幕只要在名单里就行（OBS 设置里的「直播间」）
                if admin or (viewer and hub.xroom_allowed(int(want))) or (client_kind == 'obs' and hub.xroom_listed(int(want))):
                    try:
                        h = await side_hub(int(want))
                    except Exception as e:
                        await ws.send_json({'type': 'result', 'data': {'cmd': 'connect', 'ok': False, 'msg': f'切换直播间失败：{e}'}})
                elif viewer:
                    await ws.send_json({'type': 'result', 'data': {'cmd': 'connect', 'ok': False, 'msg': f'这个直播间现在不能切过去，先看{BRAND["short"]}这边'}})
            if client_kind in ('obs', 'obs-songs', 'obs-music'):
                h.obs_clients[ws] = client_kind
                try:
                    gm = max(0.0, min(100000.0, float(request.query.get('gm', '0') or 0)))
                except ValueError:
                    gm = 0.0
                h.obs_opts[ws] = {'price': request.query.get('price') == '1', 'gm': gm}
            if viewer:
                h.viewers.add(ws)
            h.sockets[ws] = admin
            if link_id:
                h.link_sockets[ws] = link_id
            snap = h.state.snapshot()
            snap['songs'] = h.songs_view()
            if viewer:
                snap = viewer_snapshot(snap)
            elif not admin:
                snap = public_view(snap)
                o = h.obs_opts.get(ws)
                if o and not o['price']:
                    snap = obs_view('snapshot', snap, o['gm'])
            snap['admin'] = admin
            snap['sc_icons'] = hub.sc_icons
            snap['tags'] = hub.tags.view()  # 身份标签（2026-11-26）：名字、颜色、谁有什么标签
            # 主播专属链接（2026-11-18）：页面藏掉后台的东西；记下这次打开
            host = bool(link_id and links.is_host(link_id))
            snap['host'] = host
            if host:
                links.record_open(link_id, where=open_where(request))
            snap['guardlist'] = viewer_view('guardlist', h.guardlist) if viewer else h.guardlist  # 舰长名单 B 站上本来就公开（不带到期时间）
            snap['ver'] = page_vers()
            snap['app_version'] = updates.VERSION
            snap['mascot'] = mascot_ver(mascot_dir)  # 换过看板娘时网页拿它刷新图标
            if admin:
                snap['update'] = new_release[0]  # GitHub 上有新版本时：{'v', 'url', 'name'}，没有就是 None
                snap['songbook'] = hub.songbook_list()
                snap['library'] = hub.library_list()
            snap['emots'] = {**hub.emots, **h.emots}
            if not viewer:
                snap['req_rules'] = hub.req_rules
            snap['music'] = hub.music.view()
            if admin:
                snap['music_rules'] = hub.music.admin_view()
                snap['platforms'] = hub.platforms.view()
            snap['dm_more'] = h is hub and not viewer and len(hub.dmlog.items) > len(snap['dm'])  # 前面还有更早的弹幕，往上翻能加载（普通链接不能翻）
            if admin:
                snap['notes'] = hub.notes.data
                snap['public_url'] = args.public_url  # 「复制普通链接」用
                snap['lan'] = {'on': lan['on'], 'url': lan_url()}
                if local:
                    snap['desktop'] = desktop_info()
                snap['connections'] = limits.snapshot()
                snap['profiles'] = [] if hub.profiles.load_error else hub.profiles.listing()
                snap['title_presets'] = hub.title_presets
            snap['side'] = getattr(h, 'side_info', None)  # 正在看别的直播间（整页切过去）
            snap['xrooms'] = hub.xrooms if admin else viewer_view('xrooms', hub.xrooms)
            if h is not hub:
                snap['notes'] = {}
                snap['title_presets'] = []
            await ws.send_str(json.dumps({'type': 'snapshot', 'data': snap}, ensure_ascii=False))
            rate = OperationRate()
            mute_query = MuteQuery()
            async for msg in ws:
                if not h.socket_allowed(ws):
                    break
                if msg.type != aiohttp.WSMsgType.TEXT or not admin:
                    continue  # 下面这些操作都只有管理身份能做
                now = time.monotonic()
                if not rate.allow(now):
                    if rate.should_notify(now):
                        info = {}
                        # 超频时只从小消息取请求编号，不再解析大批量导入。
                        if len(msg.data) <= WS_NORMAL_LIMIT // 4:
                            try:
                                info = operation_info(parse_operation(msg.data))
                            except OperationError:
                                pass
                        await ws.send_json({'type': 'result', 'data': {**info, 'ok': False, 'msg': '操作太快，请稍后再试'}})
                    continue
                try:
                    c = parse_operation(msg.data)
                    validation.validate_command(c, clean_rules)
                except (OperationError, ValueError) as e:
                    await ws.send_json({'type': 'result', 'data': {**(e.info if isinstance(e, OperationError) else operation_info(c)), 'ok': False, 'msg': str(e)}})
                    continue
                cmd = c['cmd']
                if h is not hub:
                    await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': False, 'msg': f'正在看别的直播间，回到{BRAND["short"]}再操作'}})
                    continue
                if link_id and links.is_host(link_id) and (cmd.startswith('admin_link_') or cmd == 'reset'):
                    await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': False, 'msg': '这个链接不能做这个操作'}})
                    continue
                if args.demo and cmd in ('say', 'mute', 'room_edit', 'live_start', 'live_stop', 'areas', 'acct_qr', 'acct_poll', 'acct_info', 'acct_logout', 'news_set', 'music_qr', 'music_poll'):
                    await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': False, 'msg': '演示模式不连接真实直播间或账号'}})
                    continue
                if cmd == 'reset':
                    try:
                        hub.new_session('手动清零')
                    except OSError:
                        await ws.send_json({'type': 'result', 'data': {'cmd': 'reset', 'ok': False, 'msg': '存档失败，本场未清零，请查看自检'}})
                else:
                    try:
                        if cmd in ('tags_set', 'tag_user'):  # 身份标签（2026-11-26）
                            try:
                                if cmd == 'tags_set':
                                    hub.tags.set_config(c)
                                    msg = '身份标签已保存'
                                else:
                                    hub.tags.set_user(c.get('uid'), c.get('tags'), c.get('bot'))
                                    msg = '已经改好了'
                                hub.tags_changed()
                                await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': True, 'msg': msg}})
                            except (ValueError, OSError) as e:
                                await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': False, 'msg': str(e)}})
                            continue
                        if cmd == 'xrooms_set':
                            note = hub.xrooms_set(c)
                            await kick_side_viewers()
                            asyncio.get_event_loop().create_task(fill_xroom_names())
                            await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': True, 'msg': note}})
                            continue
                        if cmd == 'tpre_set':
                            note = hub.tpre_set(c['list'])
                            await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': True, 'msg': note}})
                            continue
                        if cmd == 'gift_thank':
                            note = hub.gift_thank_cmd(c)
                            await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': True, 'msg': note}})
                            continue
                        if cmd in ('sc_read', 'sc_read_all'):
                            note = hub.sc_read_cmd(c)
                            await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': True, 'msg': note}})
                            continue
                        if cmd in ('mute_list', 'unmute'):
                            selected = None
                            if not args.demo and c.get('acct'):
                                selected = accounts.get(c['acct'])
                                if not selected:
                                    await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': False, 'msg': '所选账号登录已失效，请重新扫码登录'}})
                                    continue
                            if cmd == 'mute_list':
                                ok, note, extra = await moderation.listing(mute_query, selected)
                            else:
                                ok, note = await moderation.unmute(mute_query, c['id'], selected)
                                extra = {}
                            await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': ok, 'msg': note, **extra}})
                            continue
                        if cmd in ('update_download', 'update_restart', 'open_mode', 'make_shortcut'):
                            # 桌面版（2026-11-25）：只有在这台电脑上打开的才能用（会下载文件、动这台电脑）
                            if not local:
                                await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': False, 'msg': '只能在运行雾幕的这台电脑上操作'}})
                                continue
                            ok, note = await desktop_cmd(c)
                            await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': ok, 'msg': note}})
                            continue
                        if cmd == 'lan_set':
                            ok, note = await lan_set(c.get('on') is True)
                            hub.emit_admin('lan', {'on': lan['on'], 'url': lan_url()})
                            await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': ok, 'msg': note}})
                            continue
                        if cmd.startswith('admin_link_'):
                            result = links.command(c, args.public_url or lan_url(), link_id, args.key)
                            if result.get('url', '').startswith('http'):
                                try:
                                    result['qr'] = qr_svg(result['url'])
                                except Exception:  # 没装 qrcode 就不给二维码，链接照样能复制
                                    pass
                            closed = hub.invalidate_links()
                            try:
                                await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': True, 'msg': '管理链接已更新', **result}})
                            finally:
                                await hub.close_links(closed)
                            continue
                        if cmd in ('profile_list', 'profile_get', 'profile_save', 'profile_delete'):
                            result, changed = hub.profiles.command(cmd, c, admin)
                            if changed:
                                hub.emit_admin('profiles', hub.profiles.listing())
                            await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': True, 'msg': '设置方案已同步', **result}})
                            continue
                        if cmd == 'plat_show':
                            ok = await hub.platforms.show('douyin', str(c.get('room')), c.get('show'))
                            await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': ok,
                                                'msg': ('抖音窗口拿出来了：在里面登录或者过验证，弄好点「藏起来」' if c.get('show') else '抖音窗口藏回去了') if ok else '这个抖音直播间还没连上，等一下再点'}})
                            continue
                        if cmd == 'plat_set':
                            try:
                                hub.platforms.set_rooms(c.get('rooms') or [])
                                hub.emit_admin('platforms', hub.platforms.view())
                                await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': True, 'msg': '其他平台的直播间已保存'}})
                            except (ValueError, OSError) as e:
                                await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': False, 'msg': str(e)}})
                            continue
                        if cmd in ('music_rules', 'music_next', 'music_ok', 'music_del', 'music_top'):
                            try:
                                msg = hub.music.command(c)
                                await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': True, 'msg': msg}})
                            except ValueError as e:
                                await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': False, 'msg': str(e)}})
                            continue
                        if cmd in ('music_qr', 'music_poll', 'music_logout', 'music_cookie'):
                            p = hub.music.providers[c['src']]
                            try:
                                if cmd == 'music_cookie':
                                    ok_c, msg_c = await hub.music.set_cookie(c['src'], c.get('cookie', ''))
                                    extra = {'state': 'ok' if ok_c else 'fail', 'msg': msg_c}
                                elif cmd == 'music_logout':
                                    hub.music.logout(c['src'])
                                    hub.emit_admin('music_rules', hub.music.admin_view())
                                    extra = {'state': 'out', 'msg': '已退出'}
                                elif cmd == 'music_qr':
                                    key, qr = await p.qr_start()
                                    extra = {'state': 'wait', 'key': key, **qr, 'msg': '用手机扫码'}
                                else:
                                    st, msg = await p.qr_poll(c['key'])
                                    extra = {'state': st, 'msg': msg}
                                await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': True, 'src': c['src'], **extra}})
                            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ImportError) as e:
                                await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': False, 'src': c['src'], 'state': 'fail', 'msg': f'登录没成功：{e}'}})
                            continue
                        if cmd in ('song_add', 'song_done', 'song_del', 'song_clear', 'song_now', 'song_next', 'song_move'):
                            changed = hub.song_cmd(cmd, str(c.get('id', '')), str(c.get('text', '')), c)
                            await ws.send_json({'type': 'result', 'data': {'cmd': cmd, 'ok': True, 'msg': changed or '歌单已同步', 'rid': c.get('rid')}})
                            continue
                        if cmd in ('library_save', 'library_delete', 'library_import'):
                            result = hub.library_cmd(cmd, c)
                            await ws.send_json({'type': 'result', 'data': {'cmd': cmd, 'ok': True, 'msg': result, 'rid': c.get('rid')}})
                            continue
                        if cmd == 'obs_test':
                            n = hub.obs_test()
                            await ws.send_json({'type': 'result', 'data': {'cmd': cmd, 'ok': bool(n), 'msg': f'已发到 {n} 个 OBS 弹幕页，去 OBS 里看看' if n else '没找到打开着的 OBS 弹幕页：先在 OBS 里加上浏览器源', 'rid': c.get('rid')}})
                            continue
                        if cmd == 'req_rules':
                            result = hub.set_req_rules(c)
                            await ws.send_json({'type': 'result', 'data': {'cmd': cmd, 'ok': True, 'msg': result, 'rid': c.get('rid')}})
                            continue
                        if cmd in ('req_done', 'req_del', 'req_clear'):
                            hub.req_cmd(cmd, str(c.get('id', '')), str(c.get('kind', '')))
                            continue
                        if cmd == 'note_set':  # 给观众写备注（空的就是删掉）
                            if int(c.get('uid', 0) or 0):
                                hub.notes.set(int(c['uid']), c.get('name', ''), c.get('text', ''))
                                hub.emit_admin('notes', hub.notes.data)
                            continue
                        acct = accounts.get(str(c.get('acct', ''))) if c.get('acct') else None
                        if cmd in ('say', 'mute', 'live_start', 'live_stop', 'room_edit', 'news_set') and c.get('acct') and not acct:
                            await ws.send_json({'type': 'result', 'data': {**operation_info(c), 'ok': False, 'msg': '所选账号登录已失效，请重新扫码登录'}})
                            continue
                        extra = {}
                        if cmd == 'say':
                            if acct:
                                ok, note = await own_say(acct, str(c.get('text', '')), int(c.get('reply_uid') or 0), str(c.get('reply_dmid') or ''))
                            else:
                                ok, note = await bot_say(str(c.get('text', '')))
                        elif cmd == 'news_get':
                            ok, note, extra = await news_get()
                        elif cmd == 'news_set':
                            ok, note = await news_set(acct, str(c.get('text', '')))
                        elif cmd == 'mute':
                            ok, note = await mute_user(int(c.get('uid', 0)), str(c.get('name', '')), acct)
                        elif cmd == 'areas':
                            ok, note, extra = await area_list()
                        elif cmd == 'room_edit':
                            ok, note = await room_edit(acct, c.get('title'), c.get('area_id'))
                        elif cmd == 'live_start':
                            ok, note, extra = await live_start(acct, c.get('area_id'), c.get('title'))
                        elif cmd == 'live_stop':
                            ok, note = await live_stop(acct)
                        elif cmd == 'acct_qr':
                            ok, note, extra = await qr_new()
                        elif cmd == 'acct_poll':
                            ok, note, extra = await qr_poll(str(c.get('key', '')))
                        elif cmd == 'acct_info':
                            ok, note, extra = await acct_info(str(c.get('acct', '')), acct)
                        elif cmd == 'acct_logout':
                            accounts.delete(str(c.get('acct', '')))
                            ok, note = True, '已退出登录'
                        else:
                            continue
                        await ws.send_str(json.dumps({'type': 'result', 'data': {'cmd': cmd, 'ok': ok, 'msg': note, **extra}}, ensure_ascii=False))
                    except Exception as e:
                        log.warning('处理网页操作出错：%s', e)
                        await ws.send_json({'type': 'result', 'data': {'cmd': c.get('cmd', ''), 'rid': c.get('rid'), 'ok': False, 'msg': str(e) if isinstance(e, ValueError) else '操作未能保存，请重试并检查磁盘状态'}})
        finally:
            if link_id and links.is_host(link_id):
                links.touch(link_id)  # 关掉时也记一下时间：10 分钟内再打开算同一次
            h.drop_socket(ws)
            await ws.close()
        return ws

    # 发弹幕：不自己发，交给机器人的弹幕助手（控制面板的接口），这样发言间隔由机器人统一管，不会抢它的频率
    say_at = [0.0]

    async def bot_say(text):
        text = text.strip()
        if not text or len(text) > 40:
            return False, '写一句话，最多 40 个字'
        if time.time() - say_at[0] < 5:
            return False, '发太快了，隔 5 秒再发'
        if not BOT_SAY_URL:
            return False, '没有设置代发弹幕的接口（config.json 的 bot_say_url）'
        try:
            with open(os.path.join(DIR, 'bot.token'), encoding='utf-8') as f:
                token = f.read().strip()
        except OSError:
            token = ''
        say_at[0] = time.time()
        try:
            async with session.post(BOT_SAY_URL, json={'text': text, 'from': '直播姬'},
                                    headers={'X-Local-Token': token}, timeout=aiohttp.ClientTimeout(total=20)) as r:
                j = await r.json(content_type=None)
                if r.status == 401:
                    return False, '机器人那边还没开放这个入口（要等机器人更新）'
                if r.status != 200 or not j.get('ok'):
                    return False, str(j.get('error') or f'没发出去（{r.status}）')
                log.info('从雾幕发了弹幕：%s', text)
                return True, j.get('note') or '已发出'
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False, '连不上机器人的控制面板，机器人可能没在运行'

    # ---- 自己的号：扫码登录 + 发弹幕（不经过机器人；B 站按账号限频，跟机器人的号互不影响） ----
    bare = aiohttp.ClientSession(headers={'User-Agent': UA}, cookie_jar=aiohttp.DummyCookieJar())  # 不带机器人的登录信息
    moderation = MuteService(hub, bare, args.room, load_cookie, demo=args.demo)
    own_at = {}

    async def qr_new():
        import io
        import qrcode
        import qrcode.image.svg
        async with bare.get('https://passport.bilibili.com/x/passport-login/web/qrcode/generate',
                            headers={'Referer': 'https://www.bilibili.com/'}, timeout=aiohttp.ClientTimeout(total=15)) as r:
            g = await r.json(content_type=None)
        if g.get('code') != 0:
            return False, f"生成二维码失败：{g.get('message')}", {}
        buf = io.BytesIO()
        qrcode.make(g['data']['url'], image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2).save(buf)
        return True, '用 B 站 App 扫一扫', {'key': g['data']['qrcode_key'], 'svg': buf.getvalue().decode('utf-8')}

    async def qr_poll(key):
        async with bare.get('https://passport.bilibili.com/x/passport-login/web/qrcode/poll',
                            params={'qrcode_key': key}, headers={'Referer': 'https://www.bilibili.com/'},
                            timeout=aiohttp.ClientTimeout(total=15)) as r:
            body = await r.json(content_type=None)
            sets = r.headers.getall('Set-Cookie', [])
        code = (body.get('data') or {}).get('code')
        if code == 86090:
            return False, '已扫码，在手机上点确认', {'state': 'scanned'}
        if code == 86038:
            return False, '二维码过期了，重新生成一个', {'state': 'expired'}
        if code != 0:
            return False, '等待扫码', {'state': 'wait'}
        jar = {}
        for c in sets:
            k, _, v = c.split(';', 1)[0].partition('=')
            if k in Accounts.KEEP:
                jar[k] = v
        if not jar.get('SESSDATA'):
            return False, '登录成功了但没拿到登录信息，再试一次', {'state': 'expired'}
        cookie = '; '.join(f'{k}={v}' for k, v in jar.items())
        uname = face = ''
        try:
            async with bare.get('https://api.bilibili.com/x/web-interface/nav', headers={'Cookie': cookie},
                                timeout=aiohttp.ClientTimeout(total=15)) as r:
                nd = (await r.json(content_type=None)).get('data') or {}
                uname, face = nd.get('uname', ''), nd.get('face', '')
        except Exception:
            pass
        token = accounts.save(cookie, int(jar.get('DedeUserID', 0) or 0), uname, face)
        log.info('有人在雾幕扫码登录了自己的 B 站号：%s（%s）', uname, jar.get('DedeUserID'))
        extra_note = ''
        # 2026-11-25：开源版用户反馈「左下角登录了还是打码」—— 以前扫码登录只用来发弹幕，连直播间用的是 data/bili-login.json，
        # 没放那个文件就一直打码。现在：还没有连直播间的登录（或者它失效了），就顺便用这个号连，马上重连
        if not args.demo and not LOGIN_READONLY and (not load_cookie() or hub.state.room.get('login_ok') is False):
            try:
                write_json(LOGIN_FILE, {'cookie': cookie})
                session.cookie_jar.update_cookies(make_cookies(cookie))
                asyncio.get_event_loop().create_task(reconnect_with_login())
                extra_note = '，也用这个号连直播间了，观众名字不再打码'
            except OSError as e:
                log.warning('登录信息没存上：%s', e)
        return True, f'登录好了：{uname}{extra_note}', {'state': 'done', 'token': token, 'uname': uname, 'face': face, 'uid': int(jar.get('DedeUserID', 0) or 0)}

    async def reconnect_with_login():
        """换了连直播间的登录：断开重连一次，B 站这才按登录的号发完整的名字"""
        c = getattr(hub, 'client', None)
        if c is None:
            return
        log.info('换了连直播间的登录，重新连接')
        try:
            if c.is_running:
                c.stop()
                await asyncio.wait_for(c.join(), 15)
        except (asyncio.CancelledError, Exception) as e:  # 刚停掉的连接 join 会报「已取消」，正常
            if not isinstance(e, asyncio.CancelledError):
                log.warning('断开旧连接时出错：%s', e)
        c._uid, c._need_init_room = None, True  # 让 blivedm 按新的登录重新查 uid（不清的话还是用旧的 0，照样打码）
        try:
            c.start()
        except Exception as e:
            log.warning('重新连接失败（会自动再试）：%s', e)
        try:
            async with session.get('https://api.bilibili.com/x/web-interface/nav', timeout=aiohttp.ClientTimeout(total=15)) as r:
                d = (await r.json(content_type=None)).get('data') or {}
            hub.room_update(login_ok=bool(d.get('isLogin')), bot_name=d.get('uname', ''), bot_face=d.get('face', ''))
        except Exception:
            pass

    async def acct_info(token, acct):
        """打开网页时查一下这个号：还登着没有，顺便拿最新的昵称和头像。"""
        if not acct:
            return False, '', {}
        try:
            async with bare.get('https://api.bilibili.com/x/web-interface/nav', headers={'Cookie': acct.get('cookie', '')},
                                timeout=aiohttp.ClientTimeout(total=15)) as r:
                nd = (await r.json(content_type=None)).get('data') or {}
        except Exception:  # 查不到就先当还登着
            return True, acct.get('uname', ''), {'uid': acct.get('uid', 0), 'face': acct.get('face', '')}
        if not nd.get('isLogin'):
            return False, '', {}
        if nd.get('uname') != acct.get('uname') or nd.get('face') != acct.get('face'):
            acct.update(uname=nd.get('uname', ''), face=nd.get('face', ''))
            write_json(accounts._path(token), acct)
        return True, acct['uname'], {'uid': acct.get('uid', 0), 'face': acct.get('face', '')}

    # ---- 改直播间标题 / 分区：B 站只让主播本人改，所以要主播自己扫码登录的号 ----
    areas = {}

    async def area_list():
        if not areas.get('list'):
            async with bare.get('https://api.live.bilibili.com/room/v1/Area/getList', timeout=aiohttp.ClientTimeout(total=15)) as r:
                j = await r.json(content_type=None)
            areas['list'] = [{'id': int(p['id']), 'name': p['name'], 'list': [{'id': int(x['id']), 'name': x['name']} for x in p.get('list') or []]}
                             for p in j.get('data') or []]
        return bool(areas['list']), '', {'areas': areas['list']}

    async def room_edit(acct, title, area_id):
        if not acct or acct.get('uid') != state.room.get('uid'):
            return False, '要主播本人的号才能改'
        m = re.search(r'bili_jct=([^;]+)', acct.get('cookie', ''))
        if not m:
            return False, '登录信息不完整，重新扫码'
        room = state.room.get('room_real') or args.room
        data = {'room_id': str(room), 'platform': 'pc', 'csrf': m.group(1), 'csrf_token': m.group(1)}
        title = str(title or '').strip()
        if title and title != state.room.get('title'):
            if len(title) > 40:
                return False, '标题最多 40 个字'
            data['title'] = title
        if area_id and int(area_id) != state.room.get('area_id'):
            data['area_id'] = str(int(area_id))
        if 'title' not in data and 'area_id' not in data:
            return True, '没有变化'
        try:
            async with bare.post('https://api.live.bilibili.com/room/v1/Room/update', data=data,
                                 headers={'Cookie': acct['cookie'], 'Origin': 'https://link.bilibili.com',
                                          'Referer': 'https://link.bilibili.com/p/center/index'},
                                 timeout=aiohttp.ClientTimeout(total=15)) as r:
                j = await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False, '连不上 B 站，稍后再试'
        if j.get('code') != 0:
            return False, str(j.get('message') or j.get('msg') or f"B 站没同意（{j.get('code')}）")
        log.info('%s 从雾幕改了直播间信息：%s', acct.get('uname'), {k: data[k] for k in ('title', 'area_id') if k in data})
        hub.wake.set()  # 马上重新查一次直播间信息，网页上跟着变
        return True, '改好了'

    # ---- 一键开播 / 下播（2026-11-18）：用主播本人扫码登录的号调 B 站开播接口，拿到推流地址和推流码交给网页（网页再让 OBS 开推）----
    # B 站 2025-05-26 起第三方开播只给粉丝 ≥5000 的主播；接口按直播姬（pc_link）的方式签名。推流码只回给点按钮的那个网页，不写日志。
    LINK_APPKEY, LINK_SECRET = 'aae92bc66f3edfab', 'af125a0d5279fd576c1b4418a3e8276d'
    link_ver = {}

    async def link_version():
        if not link_ver or time.time() - link_ver.get('at', 0) > 86400:
            try:
                async with bare.get('https://api.live.bilibili.com/xlive/app-blink/v1/liveVersionInfo/getHomePageLiveVersion',
                                    params={'system_version': '2'}, headers={'User-Agent': 'Mozilla/5.0'},
                                    timeout=aiohttp.ClientTimeout(total=15)) as r:
                    d = (await r.json(content_type=None)).get('data') or {}
                if d.get('curr_version') and d.get('build'):
                    link_ver.update(version=str(d['curr_version']), build=str(d['build']), at=time.time())
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                pass
        return link_ver.get('version', '8.15.0.11311'), link_ver.get('build', '11311')

    def link_sign(params):
        import hashlib
        from urllib.parse import urlencode
        p = {**params, 'appkey': LINK_APPKEY, 'ts': str(int(time.time()))}
        q = urlencode(sorted(p.items()))
        p['sign'] = hashlib.md5((q + LINK_SECRET).encode()).hexdigest()
        return p

    async def link_post(acct, path, params):
        m = re.search(r'bili_jct=([^;]+)', acct.get('cookie', ''))
        if not m:
            return None, '登录信息不完整，退出后重新扫码'
        version, build = await link_version()
        base = {**params, 'csrf': m.group(1), 'csrf_token': m.group(1), 'version': version, 'build': build}
        headers = {'Cookie': acct['cookie'], 'Origin': 'https://link.bilibili.com',
                   'Referer': 'https://link.bilibili.com/p/center/index', 'User-Agent': 'Mozilla/5.0'}
        j = None
        for data in (link_sign(base), base):  # 先按直播姬签名；B 站说签名不对（-3）再不签名试一次
            try:
                async with bare.post('https://api.live.bilibili.com/room/v1/Room/' + path, data=data, headers=headers,
                                     timeout=aiohttp.ClientTimeout(total=20)) as r:
                    j = await r.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                return None, '连不上 B 站，稍后再试'
            if not isinstance(j, dict):
                return None, 'B 站返回的东西看不懂，稍后再试'
            if j.get('code') != -3:
                break
        return j, ''

    def face_qr(uid):
        import io
        import qrcode
        import qrcode.image.svg
        url = f'https://www.bilibili.com/blackboard/live/face-auth-middle.html?source_event=400&mid={int(uid)}'
        buf = io.BytesIO()
        qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2).save(buf)
        return buf.getvalue().decode('utf-8')

    async def live_start(acct, area_id, title):
        if not acct or acct.get('uid') != state.room.get('uid'):
            return False, '要主播本人的号才能开播', {}
        area_id = int(area_id or 0) or int(state.room.get('area_id') or 0)
        if not area_id:
            return False, '先选一个分区', {}
        title = str(title or '').strip()
        if title and title != state.room.get('title'):
            ok, note = await room_edit(acct, title, 0)
            if not ok:
                return False, '改标题没成功：' + note, {}
        room = state.room.get('room_real') or args.room
        j, err = await link_post(acct, 'startLive', {'room_id': str(room), 'platform': 'pc_link', 'area_v2': str(area_id),
                                                     'backup_stream': '0'})
        if j is None:
            return False, err, {}
        d = j.get('data') if isinstance(j.get('data'), dict) else {}
        if j.get('code') != 0:
            if j.get('code') == -101:
                return False, '这个号的登录过期了，退出后重新扫码登录', {}
            if j.get('code') == 60043:  # 2026-11-18 实测：B 站风控要人脸认证，只能在官方 App / 直播姬里点开播完成
                return False, 'B 站这次要先做人脸认证：用手机 B 站 App（我的 → 直播中心 → 开播）或直播姬点一次开播完成认证，再回来点开播', {}
            return False, f"B 站没让开播（{j.get('code')} {j.get('message') or j.get('msg') or ''}）", {}
        if d.get('need_face_auth'):
            return False, 'B 站要先做人脸认证：用手机 B 站 App 扫下面的码，认证完再点一次开播', {'face_qr': face_qr(acct.get('uid'))}
        rtmp = d.get('rtmp') if isinstance(d.get('rtmp'), dict) else {}
        addr, code = str(rtmp.get('addr') or ''), str(rtmp.get('code') or '')
        if not addr or not code:
            return False, 'B 站说开播了，但没给推流码；去 B 站直播中心看一下', {}
        log.info('%s 从雾幕开播了（分区 %s）', acct.get('uname'), area_id)
        hub.wake.set()
        return True, '开播了', {'addr': addr, 'code': code}

    async def live_stop(acct):
        if not acct or acct.get('uid') != state.room.get('uid'):
            return False, '要主播本人的号才能下播'
        room = state.room.get('room_real') or args.room
        j, err = await link_post(acct, 'stopLive', {'room_id': str(room), 'platform': 'pc_link'})
        if j is None:
            return False, err
        if j.get('code') != 0:
            return False, f"B 站没让下播（{j.get('code')} {j.get('message') or j.get('msg') or ''}）"
        log.info('%s 从雾幕下播了', acct.get('uname'))
        hub.wake.set()
        d = j.get('data') if isinstance(j.get('data'), dict) else {}
        return True, '下播了' if d.get('change') else '现在本来就没在播'

    async def own_say(acct, text, reply_uid=0, reply_dmid=''):
        return await send_own_danmaku(bare, state, args.room, own_at, acct, text, reply_uid, reply_dmid)

    # 直播间公告（2026-11-21）：读谁都能读；改要主播本人的号（扫码登录过）
    async def news_get():
        return await get_room_news(bare, state, args.room)

    async def news_set(acct, text):
        return await set_room_news(bare, state, args.room, acct, text)

    # 禁言：登录了自己的号就用自己的号（要是这个直播间的主播或房管），没登录就用机器人那个号（也要是房管）。
    # 每次都是管理身份的人在网页上点两下才会执行。
    async def mute_user(uid, name, acct=None):
        return await moderation.mute(uid, name, acct)

    # ---- 舰长名单：现在有哪些舰长 / 提督 / 总督，陪伴了多少天，什么时候到期 ----
    # 准确的到期时间 B 站只告诉主播本人：主播在雾幕扫码登录过自己的号就用它查；
    # 没有的话，用雾幕自己记下的上舰 / 续费时间估（标「约」），再没有就只显示陪伴天数。
    def fill_guard_days(items):
        return complete_guard_days(hub, items)

    async def poll_guards():
        while True:
            hub.guard_wake.clear()
            try:
                ruid, room = state.room.get('uid'), state.room.get('room_real') or args.room
                if ruid:
                    anchor = accounts.of_uid(ruid)
                    http, headers = (bare, {'Cookie': anchor.get('cookie', '')}) if anchor else (session, {})
                    rows, seen = [], set()
                    for page in range(1, 60):
                        url = ('https://api.live.bilibili.com/xlive/app-room/v2/guardTab/topListNew'
                               f'?roomid={room}&page={page}&ruid={ruid}&page_size=20&typ=5&platform=web')
                        async with http.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as r:
                            payload = await r.json(content_type=None)
                            if r.status != 200 or not isinstance(payload, dict) or payload.get('code') != 0 or not isinstance(payload.get('data'), dict):
                                raise ValueError('舰长名单查询未成功，保留原名单')
                            g = payload['data']
                        batch = (g.get('top3') or [] if page == 1 else []) + (g.get('list') or [])
                        fresh = [x for x in batch if (x.get('uinfo') or {}).get('uid') not in seen]
                        for x in fresh:
                            ui = x.get('uinfo') or {}
                            base, gd = ui.get('base') or {}, ui.get('guard') or {}
                            seen.add(ui.get('uid'))
                            until, est = int(live_ts(gd.get('expired_str', ''))), False
                            if not until:
                                until, est = hub.guardbook.until(ui.get('uid')), True
                                if until < time.time():
                                    until = 0
                            rows.append({'uid': ui.get('uid'), 'name': base.get('name', ''), 'face': base.get('face', ''),
                                         'level': gd.get('level') or 3, 'days': x.get('accompany', 0),
                                         'until': until, 'est': est and bool(until)})
                        if not fresh or len(rows) >= ((g.get('info') or {}).get('num') or 0):
                            break
                    rows = validation.clean_rows(rows, validation.guard_list_row, 20000)
                    if hub.guard_recovery:
                        for row in rows:
                            row['recovered'] = True
                        hub.guard_recovery = False
                    if rows != hub.guardlist:
                        hub.guardlist = rows
                        hub.emit('guardlist', rows)
                    if fill_guard_days(state.guards):
                        hub.emit('guards_all', state.guards)
            except Exception as e:
                log.warning('查舰长名单失败：%s', e)
            try:
                await asyncio.wait_for(hub.guard_wake.wait(), 600 if state.room.get('uid') else 20)
                if not hub.guard_recovery:
                    await asyncio.sleep(8)  # 刚上舰时名单要过几秒才更新
            except asyncio.TimeoutError:
                pass

    # 启动时把 B 站现成的小表情表拿一份（通用的 + 这个直播间的），这样没人发过的表情也认得
    async def load_emots():
        try:
            async with session.get('https://api.live.bilibili.com/xlive/web-ucenter/v2/emoticon/GetEmoticons'
                                   f'?platform=pc&room_id={args.room}', timeout=aiohttp.ClientTimeout(total=15)) as r:
                d = (await r.json(content_type=None)).get('data') or {}
            found = {}
            for pkg in d.get('data') or []:
                for e in pkg.get('emoticons') or []:
                    k = e.get('emoji') or ''
                    if k.startswith('[') and k.endswith(']') and e.get('url'):
                        found[k] = e['url']
            hub.learn_emots(found)
            log.info('小表情表：认得 %d 个', len(hub.emots))
        except Exception as e:
            log.warning('拿小表情表失败：%s', e)

    async def hist_list(request):
        validation.validate_http('hist_list', request.query, request.match_info)
        admin = is_admin(request, links, args.port)
        if not admin:
            raise web.HTTPForbidden()  # 历史场次只给管理身份（2026-11-14）
        items = history.list()
        return web.json_response({'items': items if admin else [public_view(b) for b in items], 'admin': admin})

    async def hist_get(request):
        validation.validate_http('hist_get', request.query, request.match_info)
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        sid = request.match_info['sid']
        d = history.get(sid)
        if d is None:
            raise web.HTTPNotFound()
        d = {k: v for k, v in d.items() if k != 'viewers'}  # 观众名单是给档案用的，不用发给网页
        d['has_dm'] = history.has_dm(sid)
        d['guards'] = [dict(g) for g in d.get('guards') or [] if isinstance(g, dict)]
        fill_guard_days(d['guards'])
        return web.json_response(d if is_admin(request, links, args.port) else public_view(d))

    async def offline_list(request):
        return await list_offline(request, state, hub, links, args.port)

    def dm_query(request, items):
        options = validation.validate_http('dm_older', request.query, request.match_info)
        return web.json_response(dm_page(items, **options))

    # 本场更早的弹幕（往上翻、搜索、看某个人说过的话）
    async def dm_older(request):
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()  # 整场弹幕的翻看和搜索只给管理身份
        return dm_query(request, hub.dmlog.items)

    async def watch_static():
        """网页文件换了新版就告诉所有开着的页面（它们会自己刷新）。"""
        last = page_vers()
        while True:
            await asyncio.sleep(15)
            now = page_vers()
            if now != last:
                last = now
                await asyncio.sleep(3)  # 等几个文件都换完
                hub.emit('ver', page_vers())

    # 掉线提醒从外网绕一圈访问这里，能打开就说明隧道通
    async def ping(request):
        return web.Response(text='ok', headers={'Cache-Control': 'no-store'})

    async def gift_rank(request):
        """送礼榜的周榜 / 月榜（2026-11-18）：按北京时间本周一 / 本月 1 号起，把历史场次、下播期间、这一场的送礼加起来（原价）。"""
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden(text='需要管理身份')
        rng = request.query.get('range', 'week')
        now = datetime.datetime.now(BJ)
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = (day0 - datetime.timedelta(days=day0.weekday())) if rng == 'week' else day0.replace(day=1)
        since = start.timestamp()
        totals = {}

        def add(uid, name, face, spend, guard=0):
            if not uid or not spend:
                return
            u = totals.setdefault(uid, {'uid': uid, 'name': name, 'face': face, 'spend': 0.0, 'guard': 0})
            u['spend'] = round(u['spend'] + float(spend), 2)
            u['name'] = name or u['name']
            u['face'] = face or u['face']
            u['guard'] = max(u['guard'], guard or 0)
        s = state
        current = s.archive_id
        for b in history.list():
            if b.get('start', 0) < since or (b.get('id') == current and not s.summarized):  # 这一场还没存历史的下面按本场算
                continue
            row = history.get(b['id']) or {}
            for u in row.get('rank') or []:
                add(u.get('uid'), u.get('name', ''), u.get('face', ''), u.get('spend', 0), u.get('guard', 0))
        # 下播期间另存的礼物 / SC / 上舰
        off_dir = os.path.join(DIR, 'data', 'offline', str(s.room_id))
        try:
            names = os.listdir(off_dir)
        except OSError:
            names = []
        for n in names:
            try:
                with open(os.path.join(off_dir, n), encoding='utf-8') as f:
                    off = json.load(f)
            except (OSError, ValueError):
                continue
            for g in (off.get('gifts') or []) + (off.get('guards') or []):
                if isinstance(g, dict) and g.get('t', 0) >= since:
                    add(g.get('uid'), g.get('name', ''), g.get('face', ''), g.get('yuan') or 0, g.get('guard') or g.get('level') or 0)
            for c in off.get('scs') or []:
                if isinstance(c, dict) and c.get('t', 0) >= since:
                    add(c.get('uid'), c.get('name', ''), c.get('face', ''), c.get('price') or 0)
        # 这一场：还没存进历史的按本场送礼算；已经下播存过的只算之后送的
        if not s.summarized:
            if s.session_start >= since or s.live_start >= since:
                for u in s.users.values():
                    add(u.get('uid'), u.get('name', ''), u.get('face', ''), u.get('spend', 0), u.get('guard', 0))
        else:
            for g in s.gifts + s.guards:
                if g.get('t', 0) > max(s.settled_at, since):
                    add(g.get('uid'), g.get('name', ''), g.get('face', ''), g.get('yuan') or 0, g.get('guard') or g.get('level') or 0)
        rows = sorted(totals.values(), key=lambda u: -u['spend'])[:50]
        return web.json_response({'range': rng, 'since': int(since), 'items': rows}, headers={'Cache-Control': 'no-store'})

    async def gift_anim_sample(request):
        """设置里「预览动图」用：挑几个常见礼物的动图地址（2026-11-18）。"""
        want = ['告白花束', '小花花', '打call', '牛哇牛哇', '这个好诶', '情书', '告白气球', '小电视飞船']
        def row(n):
            fx, fxj = gift_fx(0, n)
            return {'name': n, 'anim': GIFT_BY_NAME[n][1], 'img': GIFT_BY_NAME[n][0], **({'fx': fx, 'fxj': fxj} if fx else {})}
        out = [row(n) for n in want if n in GIFT_BY_NAME]
        for n in GIFT_BY_NAME:
            if len(out) >= 8:
                break
            if n and all(o['name'] != n for o in out):
                out.append(row(n))
        return web.json_response(out[:8], headers={'Cache-Control': 'no-store'})

    # OBS 歌单「唱片」样式用的歌曲封面（2026-11-19）：按歌名（有歌手就带上）去网易云搜一下专辑封面，记在 data/song-covers.json。
    # 只查现在歌单里有的歌，免得被人拿来当搜索代理；查不到就回空，页面上还是原来的黑胶唱片。
    cover_file = os.path.join(DIR, 'data', 'song-covers.json')
    try:
        with open(cover_file, encoding='utf-8') as f:
            covers = {str(k)[:120]: v for k, v in (json.load(f) or {}).items() if isinstance(v, dict)}
    except (OSError, ValueError, AttributeError):
        covers = {}

    async def find_cover(name, artist):
        """先查 QQ 音乐（周杰伦这类网易云没有原版的也有），再查网易云。填了歌手就只认歌手对得上的；版本优先原版（不要 Live、Demo、翻唱）。"""
        norm = lambda x: re.sub(r'\s+', '', str(x or '')).casefold()
        bad = re.compile(r'[（(\[].*(live|demo|原唱|翻自|cover|女声|男声|伴奏|dj|remix|钢琴|治愈|正式版|片段|环绕)', re.I)

        def pick(rows):  # rows: [(歌名, [歌手], 封面)]
            best, best_sc = None, -99
            for n_, ars, pic in rows:
                if not pic:
                    continue
                ars_n = [norm(a) for a in ars]
                if artist and not any(norm(artist) in a or a in norm(artist) for a in ars_n if a):
                    continue  # 填了歌手：歌手对不上的不要
                sc = (4 if norm(n_) == norm(name) else 1 if norm(n_).startswith(norm(name)) else -5) - (3 if bad.search(n_) else 0)
                if sc > best_sc:
                    best, best_sc = pic, sc
            return best if best_sc > 0 else ''
        q = f'{name} {artist}'.strip()
        try:
            async with bare.get('https://c.y.qq.com/soso/fcgi-bin/client_search_cp', params={'w': q, 'format': 'json', 'n': '10', 'p': '1', 'cr': '1'},
                                headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://y.qq.com/'}, timeout=aiohttp.ClientTimeout(total=10)) as r:
                j = await r.json(content_type=None)
            rows = [(s_.get('songname', ''), [a.get('name', '') for a in s_.get('singer') or []],
                     f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{s_['albummid']}.jpg" if re.fullmatch(r'[0-9A-Za-z]{10,20}', str(s_.get('albummid') or '')) else '')
                    for s_ in (((j.get('data') or {}).get('song') or {}).get('list') or [])]
            got = pick(rows)
            if got:
                return got
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, AttributeError, TypeError):
            pass
        async with bare.get('https://music.163.com/api/cloudsearch/pc', params={'s': q, 'type': '1', 'limit': '10'},
                            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://music.163.com/'},
                            timeout=aiohttp.ClientTimeout(total=10)) as r:
            j = await r.json(content_type=None)
        rows = [(s_.get('name', ''), [a.get('name', '') for a in s_.get('ar') or []], str(((s_.get('al') or {}).get('picUrl')) or ''))
                for s_ in (((j.get('result') or {}).get('songs') or []) if isinstance(j, dict) else [])]
        pic = pick(rows)
        return pic.replace('http://', 'https://', 1) + '?param=300y300' if pic else ''

    async def song_cover(request):
        name = str(request.query.get('name', '')).strip()[:60]
        artist = str(request.query.get('artist', '')).strip()[:40]
        demo_names = ('稻香', '晴天', '告白气球', '起风了', '小幸运')  # OBS 设置页预览用的示例歌单
        if not name or not (name in demo_names or any(str(x.get('name', '')).strip() == name for x in state.songs)):
            raise web.HTTPNotFound()
        key = f'{name}|{artist}'.casefold()
        hit = covers.get(key)
        if not hit or (not hit.get('url') and time.time() - hit.get('t', 0) > 86400):
            try:
                url = await find_cover(name, artist)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                url = ''
            hit = covers[key] = {'url': validation.safe_url(url) if url else '', 't': int(time.time())}
            if len(covers) > 2000:
                for k in sorted(covers, key=lambda k: covers[k].get('t', 0))[:200]:
                    covers.pop(k, None)
            try:
                write_json(cover_file, covers)
            except OSError:
                pass
        return web.json_response({'url': hit.get('url', '')}, headers={'Cache-Control': 'no-store', 'Access-Control-Allow-Origin': '*'})

    # 舰长 / 提督 / 总督的头像框和小徽章（2026-11-25）：static/art 里有自己的图就用自己的，没有就用 B 站官方的
    # （官方图不放进仓库，用的时候经 /img 去 B 站拿，存在 data/imgcache）
    official_art = {
        'frame': {1: 'https://i0.hdslb.com/bfs/live/39164ebfdd39db3d284b1221765e7e57f5a49958.png',
                  2: 'https://i0.hdslb.com/bfs/live/09937c3beb0608e267a50ac3c7125c3f2d709098.png',
                  3: 'https://i0.hdslb.com/bfs/live/80f732943cc3367029df65e267960d56736a82ee.png'},
        'guard': {g: f'https://i0.hdslb.com/bfs/activity-plat/static/20211222/627754775478985e330c25a90ec7baf0/icon-guard{g}.png'
                  for g in (1, 2, 3)},
    }

    mascot_dir = MASCOT_DIR
    if args.demo:  # 演示模式不写 data：换的图放临时文件夹，关掉就没了
        import tempfile
        mascot_dir = tempfile.mkdtemp(prefix='danmist-mascot-')

    async def art_file(request):
        name = request.match_info.get('name', '')
        icon = re.fullmatch(r'icon-(\d{2,3})\.png', name)
        if icon and int(icon.group(1)) in MASCOT_SIZES:  # 看板娘图标：换过用换的，没换过用默认的
            mine = os.path.join(mascot_dir, name)
            path = mine if os.path.isfile(mine) else static_path('art/' + name)
            return web.FileResponse(path, headers={'Cache-Control': 'no-cache'})
        m = re.fullmatch(r'(frame|guard)([123])(-s|-v2)?\.png', name)
        if not m or (m.group(1) == 'guard' and m.group(3)) or (m.group(1) == 'frame' and not m.group(3)):
            raise web.HTTPNotFound()
        local = static_path('art/' + name)
        if os.path.isfile(local):
            return web.FileResponse(local, headers={'Cache-Control': 'no-cache'})
        url = official_art[m.group(1)][int(m.group(2))]
        raise web.HTTPFound('/img?u=' + urllib.parse.quote(url, safe='') + '&s=big', headers={'Cache-Control': 'max-age=3600'})

    async def mascot_put(request):
        """传一个尺寸的看板娘图标（网页一次传 5 个尺寸）。只给管理身份"""
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        size = validation.validate_http('mascot_put', request.query, request.match_info)['size']
        body = await request.read()
        if not body or len(body) > MASCOT_MAX or not body.startswith(b'\x89PNG\r\n\x1a\n'):
            raise web.HTTPBadRequest(text='要 1 MB 以内的 PNG 图')
        os.makedirs(mascot_dir, exist_ok=True)
        path = os.path.join(mascot_dir, f'icon-{size}.png')
        tmp = path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(body)
        os.replace(tmp, path)
        v = mascot_ver(mascot_dir)
        if request.query.get('last') == '1':  # 5 张都传完才让各个网页刷新图标，不然会先拿到没换完的旧图
            hub.emit('mascot', v)
        return web.json_response({'ok': True, 'v': v})

    async def mascot_reset(request):
        """换回默认的看板娘"""
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        validation.validate_http('mascot_reset', request.query, request.match_info)
        for n in MASCOT_SIZES:
            try:
                os.remove(os.path.join(mascot_dir, f'icon-{n}.png'))
            except FileNotFoundError:
                pass
        hub.emit('mascot', 0)
        return web.json_response({'ok': True, 'v': 0})

    # 歌切合集（可选，config.json 的 gequ_dir）：别的程序生成的 index.html 和 songs.json，这里只读出来公开，
    # 粉丝站可以直接读（CORS），缓存 5 分钟。不用 GitHub、不用任何登录凭据（2026-11-13）
    async def gequ(request):
        if args.demo:
            raise web.HTTPNotFound()
        name = 'songs.json' if request.path.endswith('.json') else 'index.html'
        p = os.path.join(GEQU_DIR, name)
        if not os.path.exists(p):
            raise web.HTTPNotFound()
        return web.FileResponse(p, headers={'Cache-Control': 'public, max-age=300', 'Access-Control-Allow-Origin': '*'})

    async def diag(request):
        """导出诊断信息（2026-11-26）：版本、系统、设置（密钥藏掉）、连接状态、最近的日志。只给管理身份"""
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        import platform as pf
        room = state.room
        lines = [f'{BRAND["name"]} 诊断信息', f'时间：{time.strftime("%Y-%m-%d %H:%M:%S")}',
                 f'版本：{updates.VERSION}', f'系统：{pf.platform()}  Python {pf.python_version()}',
                 f'演示模式：{bool(args.demo)}', '',
                 '== 连接 ==', json.dumps({k: room.get(k) for k in ('live', 'bili_ok', 'login_ok', 'room_real', 'live_time')}, ensure_ascii=False),
                 '== 其他平台 ==', json.dumps(hub.platforms.view(), ensure_ascii=False),
                 '== 设置（config.json，密钥已藏掉） ==', json.dumps(redact(load_config(args.config)), ensure_ascii=False, indent=1)]
        log_file = args.log and (args.log if os.path.isabs(args.log) else os.path.join(DIR, args.log))
        lines.append('== 最近的日志（IP 已打码） ==')
        try:
            with open(log_file, encoding='utf-8', errors='replace') as f:
                lines += [mask_line(x.rstrip()) for x in collections.deque(f, 400)]
        except (OSError, TypeError):
            lines.append('（没有日志文件：用桌面版或者 start.bat 打开才会写）')
        name = time.strftime('danmist-diag-%Y%m%d-%H%M.txt')
        return web.Response(text='\n'.join(lines) + '\n', content_type='text/plain', charset='utf-8',
                            headers={'Content-Disposition': f'attachment; filename="{name}"', 'Cache-Control': 'no-store'})

    async def backups_list(request):
        """一键备份 / 恢复（2026-11-26）：列出 备份/数据 里的备份。只给管理身份"""
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        return web.json_response({'items': list_backups(), 'dir': backup_dir(), 'local': local_request(request)}, headers={'Cache-Control': 'no-store'})

    async def backup_now(request):
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        if args.demo:
            return web.json_response({'ok': False, 'msg': '演示模式不备份'})
        hub.state.save()
        hub.dmlog.flush()
        out = await asyncio.get_event_loop().run_in_executor(None, lambda: backup_data(tag='手动'))
        return web.json_response({'ok': True, 'msg': f'备份好了：{os.path.basename(out)}', 'items': list_backups()})

    async def backup_restore(request):
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        name = validation.validate_http('backup_restore', request.query, request.match_info)['name']
        if args.demo:
            return web.json_response({'ok': False, 'msg': '演示模式不恢复'})
        if not os.path.isfile(os.path.join(backup_dir(), name)):
            return web.json_response({'ok': False, 'msg': '找不到这份备份'})
        write_json(os.path.join(DIR, 'data', RESTORE_FILE), {'name': name, 't': int(time.time())})
        log.info('点了「从这份恢复」：%s，重启时换上', name)
        if not (launcher or MANAGED_RESTART):
            return web.json_response({'ok': True, 'msg': '准备好了：把雾幕关掉再打开就会换成这份（换之前会先把现在的再备份一份）'})
        hub.state.dirty = True
        hub.state.save()
        hub.dmlog.flush()
        asyncio.get_event_loop().call_later(1.0, lambda: os._exit(3))  # 退出码 3：桌面版、start.bat、守护都会马上重开
        return web.json_response({'ok': True, 'msg': '正在重启换成这份，几秒后页面自己连回来（现在的也先备份了一份）'})

    async def backup_open(request):
        """在这台电脑上打开备份文件夹（只在本机打开的页面能用）"""
        if not is_admin(request, links, args.port) or not local_request(request):
            raise web.HTTPForbidden()
        os.makedirs(backup_dir(), exist_ok=True)
        if hasattr(os, 'startfile'):
            os.startfile(backup_dir())
        return web.json_response({'ok': True})

    def local_request(request):
        return request.remote in ('127.0.0.1', '::1') and 'CF-Connecting-IP' not in request.headers

    async def lyrics_now(request):
        """OBS 歌词源（2026-11-26）：歌单里「正在唱」的那首和它在曲库里的歌词。歌词本来就是要上屏的，不用管理身份"""
        cur = next((x for x in hub.state.songs if x.get('now')), None)
        if not cur:
            return web.json_response({}, headers={'Cache-Control': 'no-store'})
        name = cur.get('name', '')
        row = hub.songbook.get(name) or next((v for k, v in hub.songbook.items() if k.casefold() == name.casefold()), None) or {}
        return web.json_response({'name': name, 'artist': row.get('artist', ''), 'lyrics': str(row.get('lyrics') or '')[:20000]},
                                 headers={'Cache-Control': 'no-store'})

    async def music_url(request):
        """放歌页来要「现在这首」的播放地址（2026-11-25）。只给正在放的那首，不能拿它去下别的歌"""
        it = hub.music.current()
        if not it or request.query.get('id') != it['id']:
            return web.json_response({'url': ''}, headers={'Cache-Control': 'no-store'})
        try:
            url = await hub.music.url_for(it)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            url = ''
        return web.json_response({'url': url, 'start': it.get('start', 0), 'now': time.time()}, headers={'Cache-Control': 'no-store'})

    async def art_list(request):
        """static/art 里自己放了哪些图（只回文件名），页面据此决定用不用 B 站官方的框"""
        try:
            dirs = [os.path.join(DIR, 'static', 'art')] + ([os.path.join(PACK, 'static', 'art')] if PACK else [])
            names = sorted({n for d in dirs if os.path.isdir(d) for n in os.listdir(d) if re.fullmatch(r'[\w-]+\.(?:png|webp)', n)})
        except OSError:
            names = []
        return web.json_response(names, headers={'Cache-Control': 'no-store'})

    async def wealth_icons(request):
        return web.json_response(WEALTH_ICON, headers={'Cache-Control': 'no-store'})

    async def guard_fx_list(request):
        return web.json_response({lv: {'fx': f[0], 'fxj': f[1]} for lv, f in GUARD_FX.items()}, headers={'Cache-Control': 'no-store'})

    async def watch_alerts():
        """每 30 秒看一眼：存档、B 站连接、机器人登录、外网（隧道）。断了一会儿就发 Discord，好了再说一声。"""
        alerts = Alerts(bare)
        await asyncio.sleep(90)  # 刚启动时先等连上
        url = args.public_url.rstrip('/') + '/api/ping'
        while True:
            try:
                await journal.report(alerts.send, demo=args.demo)
                r = state.room
                await alerts.check_archive(state, hub.dmlog)
                await alerts.check('bili', r.get('bili_ok') is False, 180,
                                   lambda m: f'⚠️ {BRAND["name"]}连不上 B 站直播间已经 {m} 分钟了，弹幕、礼物暂时收不到（会自己一直重连）。',
                                   lambda m: f'✅ {BRAND["name"]}跟 B 站的连接恢复了（断了约 {m} 分钟）。')
                await alerts.check('login', r.get('login_ok') is False, 60,
                                   lambda m: f'⚠️ {BRAND["name"]}用的 B 站登录失效了，弹幕里的名字会打码。机器人重新扫码登录后会自动恢复。',
                                   lambda m: f'✅ {BRAND["name"]}的 B 站登录恢复了（失效了约 {m} 分钟）。')
                try:
                    async with bare.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                        tunnel_ok = resp.status == 200 and (await resp.text()) == 'ok'
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    tunnel_ok = False
                await alerts.check('tunnel', not tunnel_ok, 120,
                                   lambda m: f'⚠️ 外网打不开{BRAND["name"]}了（{args.public_url}）已经 {m} 分钟，电脑上本身还在运行，可能是隧道或网络断了。',
                                   lambda m: f'✅ 外网又能打开{BRAND["name"]}了（断了约 {m} 分钟）。')
            except Exception as e:
                log.warning('掉线检查出错：%s', e)
            await asyncio.sleep(30)

    # 历史场次的整场弹幕
    async def hist_dm(request):
        validation.validate_http('hist_dm', request.query, request.match_info)
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        rows = await asyncio.to_thread(history.dm, request.match_info['sid'])
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        return dm_query(request, rows)

    # 观众档案：这个人以前各场的弹幕数、送出（只给管理身份）
    async def xrooms_list(request):
        """OBS 设置里的「直播间」能选哪些：就是切房名单（只有房间号和名字）。"""
        return web.json_response({'main': {'room': args.room, 'name': args.anchor_name or '主播'}, 'rooms': hub.xrooms['rooms']})

    async def viewer_info(request):
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        uid = validation.validate_http('viewer_info', request.query, request.match_info)['uid']
        return web.json_response({'sessions': history.viewer(uid), 'note': (hub.notes.data.get(str(uid)) or {}).get('note', '')})

    async def hist_delete(request):
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        validation.validate_http('hist_delete', request.query, request.match_info)
        if not history.delete(request.match_info['sid']):
            raise web.HTTPNotFound()
        return web.json_response({'ok': True})

    # 头像图床有防盗链，网页直接引用会挂，这里转一下
    async def img_proxy(request):
        url = validation.validate_http('img_proxy', request.query, request.match_info)['u']
        host = urllib.parse.urlsplit(url).hostname or ''
        other = url.startswith('https://') and host.endswith(('.douyucdn.cn', '.msstatic.com', '.huya.com', '.douyinpic.com'))
        if not other and not url.startswith(('https://i0.hdslb.com/', 'https://i1.hdslb.com/', 'https://i2.hdslb.com/',
                                             'https://s1.hdslb.com/', 'http://i0.hdslb.com/', 'http://i1.hdslb.com/',
                                             'http://i2.hdslb.com/')):
            raise web.HTTPBadRequest()
        # 拿过的图存在电脑上（data/imgcache），下次直接给，不用再去 B 站拿；30 天没人看的启动时清掉
        import hashlib
        # s=big：大礼物特效要原图大小（礼物动图原图 140 像素），不缩成 96（2026-11-18）
        size = '' if request.query.get('s') == 'big' or other else '@96w_96h.webp'  # 别的平台的图没有 B 站的缩图后缀
        cache = os.path.join(IMG_CACHE, hashlib.sha1((url + ('' if size else '#big')).encode()).hexdigest() + '.webp')
        long_cache = {'Cache-Control': 'max-age=2592000, immutable'}
        if os.path.exists(cache):
            try:
                os.utime(cache)
            except OSError:
                pass
            return web.FileResponse(cache, headers={**long_cache, 'Content-Type': 'image/webp'})
        try:
            async with session.get(url.replace('http://', 'https://', 1) + size,
                                   timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False) as r:
                if r.status != 200:
                    raise web.HTTPNotFound()
                body = await r.read()
                if len(body) < 300000 and str(r.content_type).startswith('image/'):
                    try:
                        os.makedirs(IMG_CACHE, exist_ok=True)
                        with open(cache + '.tmp', 'wb') as f:
                            f.write(body)
                        os.replace(cache + '.tmp', cache)
                    except OSError:
                        pass
                return web.Response(body=body, content_type=r.content_type, headers=long_cache)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise web.HTTPBadGateway()

    # 设了 key 的话，第一次用 ?key= 打开，之后记在 cookie 里
    @web.middleware
    async def auth(request, handler):
        if not args.key or request.path == '/api/launcher/quit':
            return await handler(request)
        q = request.query.get('key', '')
        k = q or request.cookies.get('xwkey', '')
        if not hmac.compare_digest(k.encode('utf-8'), args.key.encode('utf-8')):
            return web.Response(status=403, text='这个链接不对，找管理员要带 key 的链接', charset='utf-8')
        resp = await handler(request)
        if q and request.path == '/':
            resp.set_cookie('xwkey', args.key, max_age=86400 * 365, httponly=True, samesite='Lax')
        return resp

    # 管理密钥也是第一次带上之后记在 cookie 里
    @web.middleware
    async def remember_admin(request, handler):
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.path != '/api/launcher/quit' and not origin_ok(request):
            raise web.HTTPForbidden(text='请从直播姬页面操作')
        resp = await handler(request)
        a = request.query.get('admin', '')
        if a and request.path in ('/', '/host', HOST_PATH) and links.authenticate(a):
            resp.set_cookie('xwadmin', a, max_age=86400 * 365, httponly=True, samesite='Lax')
        return resp

    async def preflight(request):
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden(text='自检需要管理身份')
        now = int(time.time())
        rows = []
        def add(key, title, status, detail):
            rows.append({'id': key, 'title': title, 'status': status, 'detail': detail})
        age = int(time.time() - hub.bili_seen)
        add('bili', 'B 站弹幕连接', 'pass' if hub.bili_message_seen and age < 75 else 'warn',
            f'最近一次上游消息在 {max(0, age)} 秒前' if hub.bili_message_seen else '正在等待首条上游消息')
        login = state.room.get('login_ok')
        add('login', 'B 站登录', 'pass' if login is True else 'fail' if login is False else 'warn',
            '最近登录检查有效' if login is True else '登录已失效，请重新登录' if login is False else '尚未取得登录检查结果')
        add('room', '直播间信息', 'pass' if state.room.get('title') else 'warn',
            f"{state.room.get('title', '尚未取得标题')} · {'已开播' if state.room.get('live') else '未开播'}")
        try:
            folder = os.path.join(DIR, 'data')
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, '.preflight-' + uuid.uuid4().hex + '.tmp')
            try:
                with open(probe, 'x', encoding='utf-8') as f:
                    f.write('storage probe')
                free = shutil.disk_usage(folder).free / (1024 ** 3)
                add('storage', '数据保存', 'pass' if free >= 1 else 'warn', f'目录可写，磁盘剩余 {free:.1f} GB')
            finally:
                if os.path.exists(probe):
                    os.remove(probe)
        except OSError:
            add('storage', '数据保存', 'fail', '无法写入数据目录，请检查磁盘空间和权限')
        archive_retry = bool(state.archive_pending or getattr(hub.dmlog, 'repair_write', False))
        add('pending', '弹幕与场次存档', 'fail' if archive_retry else 'pass',
            f'{len(hub.dmlog.pending)} 条弹幕等待保存' + ('；有存档失败，正在重试' if archive_retry else '；每 5 秒保存一次'))
        backup_dir = os.path.join(DIR, '备份', '数据')
        try:
            files = [os.path.join(backup_dir, n) for n in os.listdir(backup_dir) if re.fullmatch(r'data-\d{8}\.zip', n)]
            latest = max((os.path.getmtime(f) for f in files), default=0)
        except OSError:
            latest = 0
        add('backup', '最近数据备份', 'pass' if latest and now - latest < 36 * 3600 else 'warn',
            datetime.datetime.fromtimestamp(latest, BJ).strftime('%m-%d %H:%M（北京时间）') if latest else '尚未发现自动备份')
        add('queue', '待唱歌单', 'pass' if any(not x['done'] for x in state.songs) else 'warn',
            f"{sum(not x['done'] for x in state.songs)} 首待唱，{sum(x.get('now', False) for x in state.songs)} 首正在唱")
        clients = [v for ws, v in hub.obs_clients.items() if not ws.closed]
        add('obs', '上屏页面连接', 'pass' if clients else 'warn',
            f'已连接 {len(clients)} 个上屏页面（包括浏览器预览，不能判断 OBS 是否正在推流）' if clients else '未检测到上屏页面；请在 OBS 打开浏览器源后重新检查')
        return web.json_response({'checked_at': now, 'checks': rows, 'daily_health': health.snapshot()}, headers={'Cache-Control': 'no-store'})

    @web.middleware
    async def public_rate(request, handler):
        if request.path != '/ws':
            reason = limits.http(client_ip(request, args.public_url), request.path,
                                 exempt=is_admin(request, links, args.port))
            if reason:
                return web.Response(status=429, text=reason, headers={'Retry-After': '60'})
        return await handler(request)

    async def watch_access():
        last = None
        while True:
            await hub.close_links(hub.invalidate_links())
            limits.report()
            stats = limits.snapshot()
            if stats != last:
                hub.emit_admin('connections', stats)
                last = stats
            try:
                links.maintain()
            except OSError:
                log.warning('管理链接使用时间保存失败，将稍后重试')
            await asyncio.sleep(1)

    async def watch_health():
        alerts = Alerts(bare)
        await asyncio.sleep(90)  # 启动时先给 B 站连接与机器人登录检查留出时间。
        while True:
            try:
                await health.run(state.room, bare, args.public_url, alerts.send,
                                 enabled=not args.no_alert and args.port == (ALERT_PORT or 8373))
            except Exception:
                log.warning('每日体检未完成，将稍后重试')
            await asyncio.sleep(30)

    @web.middleware
    async def input_errors(request, handler):
        try:
            validation.validate_http('common', request.query, request.match_info)
            for key in ('admin', 'key'):
                if key in request.query:
                    validation.text(request.query[key], '访问参数', 512)
            return await handler(request)
        except validation.InputError as e:
            return web.json_response({'ok': False, 'msg': str(e)}, status=400)

    # AI 音色（可选）：config.json 的 "ai_voice"，接本机的 GPT-SoVITS（见 README「AI 音色」）。
    # 只给管理身份用（不然谁都能借这个声音说任意的话）。网页拿到 wav 自己播；服务没开、太忙就退回浏览器语音
    voice_box = [AIVoice(cfg.get('ai_voice'))]  # 设置里改了地址会换一个新的（2026-11-26）
    ai_voice = voice_box[0]
    if restored:
        log.info('已经换成备份 %s（换之前的在 备份/数据 里，名字带「恢复前」）', restored)
    if ai_voice.enabled:
        log.info('AI 音色：%s（%s）', ai_voice.url, ai_voice.api)

    async def tts_voices(request):
        if not is_admin(request, links, args.port):
            return web.json_response({'ok': False, 'voices': [], 'online': False}, status=403)
        av = voice_box[0]
        rows, online = await av.voices(bare)
        return web.json_response({'ok': True, 'enabled': av.enabled, 'online': online, 'voices': rows,
                                  'url': av.url, 'api': av.api}, headers={'Cache-Control': 'no-store'})

    async def tts_config(request):
        """设置 → 朗读 → AI 音色：填地址、选接口，存进 config.json 的 ai_voice，马上换上并测一下连不连得上（2026-11-26）"""
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden()
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or set(body) - {'url', 'api'}:
            return web.json_response({'ok': False, 'msg': '格式不对'}, status=400)
        url = str(body.get('url') or '').strip().rstrip('/')
        api = 'api_v2' if body.get('api') == 'api_v2' else 'folder'
        if url and (len(url) > 200 or not re.fullmatch(r'https?://[\w.\-]+(:\d{1,5})?(/[\w./\-]*)?', url)):
            return web.json_response({'ok': False, 'msg': '地址要像 http://127.0.0.1:9880 这样'})
        if args.demo:
            return web.json_response({'ok': False, 'msg': '演示模式不改设置'})
        conf = load_config(args.config)
        av_conf = dict(conf.get('ai_voice') or {}) if isinstance(conf.get('ai_voice'), dict) else {}
        av_conf.update(url=url, api=api)  # 别的（音色列表、名字）照旧
        conf['ai_voice'] = av_conf
        write_json(args.config, conf)
        voice_box[0] = AIVoice(av_conf)
        log.info('AI 音色改成：%s（%s）', url or '不用', api)
        if not url:
            return web.json_response({'ok': True, 'online': False, 'voices': [], 'msg': '已关掉 AI 音色'})
        rows, online = await voice_box[0].voices(bare)
        msg = f'连上了，有 {len(rows)} 个音色' if online and rows else ('连上了，但是没有音色（api_v2 要在 config.json 里写 voices）' if online else '连不上：看看 GPT-SoVITS 开着没有、地址对不对')
        return web.json_response({'ok': online, 'online': online, 'voices': rows, 'msg': msg})

    async def tts_speak(request):
        if not is_admin(request, links, args.port):
            raise web.HTTPForbidden(text='AI 音色需要管理身份')
        q = request.query
        try:
            speed = float(q.get('speed') or 1)
        except ValueError:
            speed = 1.0
        try:
            wav = await voice_box[0].speak(bare, q.get('voice', ''), q.get('text', ''), speed)
        except VoiceBusy as e:
            return web.json_response({'ok': False, 'msg': str(e)}, status=503)
        except (VoiceError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning('AI 音色合成失败：%s', e or type(e).__name__)
            return web.json_response({'ok': False, 'msg': str(e) or '合成失败'}, status=502)
        return web.Response(body=wav, content_type='audio/wav', headers={'Cache-Control': 'private, max-age=3600'})

    app = web.Application(middlewares=[input_errors, public_rate, auth, remember_admin])
    app.router.add_get('/', index)
    app.router.add_get('/host', index)  # 主播专属链接用这个地址
    if HOST_PATH != '/host':
        app.router.add_get(HOST_PATH, index)  # 包里给主播专属链接换的地址（config.json 的 host_path）
    # OBS 浏览器源用的弹幕叠加页（透明背景）
    app.router.add_get('/obs', page('obs'))
    # 调 OBS 弹幕样式的设置页：调好一键复制网址
    app.router.add_get('/obs-setup', obs_setup)
    # OBS 浏览器源用的歌单页（正在唱 + 接下来几首，跟雾幕的歌单同步）
    app.router.add_get('/obs-songs', page('obs-songs'))
    app.router.add_get('/ws', ws_handler)
    app.router.add_get('/img', img_proxy)
    app.router.add_get('/art/{name}', art_file)
    app.router.add_get('/api/art', art_list)
    app.router.add_post('/api/launcher/quit', launcher_quit)
    app.router.add_post('/api/mascot', mascot_put)
    app.router.add_get('/api/diag', diag)
    app.router.add_get('/api/backups', backups_list)
    app.router.add_post('/api/backup', backup_now)
    app.router.add_post('/api/backup/restore', backup_restore)
    app.router.add_post('/api/backup/open', backup_open)
    app.router.add_post('/api/mascot/reset', mascot_reset)
    app.router.add_get('/api/history', hist_list)
    app.router.add_get('/api/offline', offline_list)
    app.router.add_get('/api/history/{sid}', hist_get)
    app.router.add_post('/api/history/{sid}/delete', hist_delete)
    app.router.add_get('/api/history/{sid}/dm', hist_dm)
    app.router.add_get('/api/dm', dm_older)
    app.router.add_get('/api/ping', ping)
    app.router.add_get('/api/gift_anims', gift_anim_sample)
    app.router.add_get('/api/guard_fx', guard_fx_list)
    app.router.add_get('/api/wealth_icons', wealth_icons)
    app.router.add_get('/api/song_cover', song_cover)
    app.router.add_get('/api/gift_rank', gift_rank)
    app.router.add_get('/api/preflight', preflight)
    app.router.add_get('/api/viewer/{uid}', viewer_info)
    app.router.add_get('/api/xrooms', xrooms_list)
    app.router.add_get('/api/tts/voices', tts_voices)
    app.router.add_get('/api/tts', tts_speak)
    app.router.add_post('/api/tts/config', tts_config)
    app.router.add_get('/api/music/url', music_url)
    app.router.add_get('/obs-music', page('obs-music'))
    app.router.add_get('/obs-lyrics', page('obs-lyrics'))  # OBS 歌词源（2026-11-26）
    app.router.add_get('/api/lyrics/now', lyrics_now)
    if GEQU_DIR:
        app.router.add_get('/gequ.html', gequ)
        app.router.add_get('/gequ.json', gequ)
    app.router.add_get('/static/{path:.+}', static_file)

    cookies = make_cookies(load_cookie()) if not args.demo else {}
    session = aiohttp.ClientSession(headers={'User-Agent': UA})
    session.cookie_jar.update_cookies(cookies)

    runner = web.AppRunner(app, access_log=None)  # 每次请求都记一行太多了
    await runner.setup()
    await web.TCPSite(runner, args.host, args.port).start()
    log.info('网页已启动：http://%s:%d  直播间 %s', args.host, args.port, 'demo' if args.demo else args.room)
    if cfg_lan and not args.demo:
        await lan_set(True, save=False)

    WEALTH_CACHE = '' if args.demo else os.path.join(DIR, 'data', 'wealth-icons.json')

    async def face_worker():
        """没头像的人去 B 站名片接口查（不带登录，慢慢查，一秒多一个），查到了补给网页（2026-11-25）"""
        card = Breaker('B 站名片接口')  # 连着失败先歇一会（2026-11-26）
        while True:
            uid = await hub.face_q.get()
            if not card.ready():
                await asyncio.sleep(card.left())
            try:
                async with bare.get('https://api.bilibili.com/x/web-interface/card', params={'mid': str(uid)},
                                    headers={'Referer': 'https://www.bilibili.com/'}, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    j = await r.json(content_type=None)
                face = validation.safe_url(str((((j or {}).get('data') or {}).get('card') or {}).get('face') or '')) if isinstance(j, dict) else ''
                if face and 'noface' not in face:
                    hub.got_face(uid, face)
                card.ok()
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                card.fail()
                log.debug('名片没查到 %s：%s', uid, e)
            await asyncio.sleep(1.5)

    if not args.demo:
        hub.face_q, hub.face_seen = asyncio.Queue(), set()
    tasks = [asyncio.create_task(watch_static()), asyncio.create_task(watch_access()), asyncio.create_task(watch_gift_anim(bare, args.room))]
    if not args.demo:
        tasks.append(asyncio.create_task(face_worker()))
    tasks.append(asyncio.create_task(hub.music.run(bare)))
    hub.platforms.apply()  # 其他平台（斗鱼、虎牙、抖音）的直播间

    async def watch_platforms():
        last = None
        while True:
            await asyncio.sleep(5)
            v = hub.platforms.view()
            if v != last:
                last = v
                hub.emit_admin('platforms', v)
    tasks.append(asyncio.create_task(watch_platforms()))
    # 有新版本就在管理页面上提示（只读 GitHub 最新 Release 的版本号，不下载任何东西）；演示模式只在测试时查
    if not args.no_update_check and (not args.demo or args.update_url):
        def on_new_release(info):
            new_release[0] = info
            hub.emit_admin('update', info)
        tasks.append(asyncio.create_task(updates.watch(bare, on_new_release, args.update_url or updates.LATEST_API,
                                                       first_delay=2 if args.update_url else updates.FIRST_DELAY)))
    client = None
    if args.demo:
        tasks.append(asyncio.create_task(demo_feed(hub)))
    else:
        if not cookies:
            log.warning('没读到 B 站登录信息（%s），用户名会打码', LOGIN_FILE)
        # 2026-11-25 用户：连直播间的号多半是主播自己扫码登录的号，不能当成机器人（以前自己发的弹幕都标「机器人」、还不朗读）。
        # 只有在 config.json 里接了单独的机器人（bot_say_url）时，连直播间的这个号才算机器人
        set_bots(state, [u for u in [uid_of(load_cookie())] if u] if BOT_SAY_URL else [])
        state.enters = [e for e in state.enters if e.get('uid') not in state.bot_uids]  # 以前记下的机器人「进房」清掉
        client = TrackedClient(hub, args.room, session)
        client.set_reconnect_policy(connection_recovery.retry_delay)
        client.set_handler(Handler(hub))
        client.start()
        hub.client = client
        tasks.append(asyncio.create_task(poll_room(hub, session, args.room)))
        tasks.append(asyncio.create_task(watch_login(session, state)))
        tasks.append(asyncio.create_task(watch_bili(hub, session)))
        tasks.append(asyncio.create_task(connection_recovery.watch_recovery(hub, session)))
        tasks.append(asyncio.create_task(poll_guards()))
        tasks.append(asyncio.create_task(load_emots()))
        tasks.append(asyncio.create_task(daily_backup(hub)))
        tasks.append(asyncio.create_task(watch_health()))
        if not args.no_alert and (DISCORD_WEBHOOK or DISCORD_WEBHOOK_FILE) and (not ALERT_PORT or args.port == ALERT_PORT):  # 填了 Discord 地址才发掉线提醒
            tasks.append(asyncio.create_task(watch_alerts()))

    for task in tasks:
        task.add_done_callback(journal.task_done)

    try:
        while True:
            await asyncio.sleep(5)
            journal.prune(time.time())
            journal.flush()
            if not args.demo:
                hub.rotate_large_segment()
            state.save()
            hub.dmlog.flush()
            if state.archive_pending:
                hub.close_broadcast('下播存档重试')
    except Exception as e:
        journal.add('CRITICAL', str(e), 'server.main')
        journal.flush()
        raise
    finally:
        hub.stopping = True
        state.save()
        hub.dmlog.flush()
        for t in tasks:
            t.cancel()
        if client:
            await client.stop_and_close()
        await session.close()
        await bare.close()
        await runner.cleanup()
        restore_errors()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
