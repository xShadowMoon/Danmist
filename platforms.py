"""其他直播平台（2026-11-25）：斗鱼、虎牙的弹幕、礼物、进房，只读，跟 B 站的混在一起显示，每条标上平台。
（抖音没做：它的弹幕要过抖音自己的反爬签名，绕过它不合适；以后可以走抖音开放平台的官方接口。）

用法：设置 → 弹幕 → 「其他平台」里加直播间（同时在好几个平台开播时用）。存在 data/platforms.json。
每个直播间一个连接，断了自动重连；平台改了协议就只是这一路收不到，不影响 B 站。
uid 加上平台号 × 10^14，跟 B 站的 uid 不会撞。
"""
import asyncio
import json
import os
import random
import re
import ssl
import struct
import time

import aiohttp

PLATS = {'douyu': ('斗鱼', 1), 'huya': ('虎牙', 2)}
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
UA_M = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
ROOMS_MAX = 6


def puid(plat, uid):
    try:
        return PLATS[plat][1] * 10 ** 14 + int(uid) % 10 ** 14
    except (TypeError, ValueError):
        return PLATS[plat][1] * 10 ** 14


def clean_rooms(rows):
    if not isinstance(rows, list) or len(rows) > ROOMS_MAX:
        raise ValueError(f'最多 {ROOMS_MAX} 个直播间')
    out, seen = [], set()
    for r in rows:
        if not isinstance(r, dict) or r.get('plat') not in PLATS:
            raise ValueError('平台不对')
        room = re.sub(r'\D', '', str(r.get('room') or ''))[:20]
        if not room:
            raise ValueError('房间号不能空')
        if (r['plat'], room) not in seen:
            seen.add((r['plat'], room))
            out.append({'plat': r['plat'], 'room': room, 'on': r.get('on') is not False})
    return out


# ---------- 斗鱼：STT 文本协议 ----------
def _dy_pack(s):
    body = s.encode('utf-8') + b'\0'
    n = len(body) + 8
    return struct.pack('<iihbb', n, n, 689, 0, 0) + body


def _dy_parse(s):
    d = {}
    for kv in s.split('/'):
        if '@=' in kv:
            k, v = kv.split('@=', 1)
            d[k.replace('@S', '/').replace('@A', '@')] = v.replace('@S', '/').replace('@A', '@')
    return d


# ---------- 虎牙：Tars 二进制协议（只写用到的类型） ----------
class _TW:
    def __init__(self):
        self.b = bytearray()

    def head(self, tag, t):
        self.b += bytes([(tag << 4) | t]) if tag < 15 else bytes([0xF0 | t, tag])

    def int(self, tag, v):
        if v == 0:
            self.head(tag, 12)
        elif -128 <= v <= 127:
            self.head(tag, 0); self.b += struct.pack('>b', v)
        elif -32768 <= v <= 32767:
            self.head(tag, 1); self.b += struct.pack('>h', v)
        elif -2 ** 31 <= v < 2 ** 31:
            self.head(tag, 2); self.b += struct.pack('>i', v)
        else:
            self.head(tag, 3); self.b += struct.pack('>q', v)
        return self

    def str(self, tag, s):
        d = s.encode('utf-8')
        if len(d) < 256:
            self.head(tag, 6); self.b.append(len(d))
        else:
            self.head(tag, 7); self.b += struct.pack('>I', len(d))
        self.b += d
        return self

    def bytes(self, tag, d):
        self.head(tag, 13); self.head(0, 0); self.int(0, len(d)); self.b += d
        return self

    def strlist(self, tag, items):
        self.head(tag, 9); self.int(0, len(items))
        for s in items:
            self.str(0, s)
        return self


def _t_head(b, i):
    h = b[i]; i += 1
    tag, t = h >> 4, h & 15
    if tag == 15:
        tag = b[i]; i += 1
    return tag, t, i


def _t_val(b, i, t):
    if t == 0:
        return struct.unpack_from('>b', b, i)[0], i + 1
    if t == 1:
        return struct.unpack_from('>h', b, i)[0], i + 2
    if t == 2:
        return struct.unpack_from('>i', b, i)[0], i + 4
    if t == 3:
        return struct.unpack_from('>q', b, i)[0], i + 8
    if t == 4:
        return struct.unpack_from('>f', b, i)[0], i + 4
    if t == 5:
        return struct.unpack_from('>d', b, i)[0], i + 8
    if t in (6, 7):
        n, i = (b[i], i + 1) if t == 6 else (struct.unpack_from('>I', b, i)[0], i + 4)
        return b[i:i + n].decode('utf-8', 'replace'), i + n
    if t == 8:
        _, lt, i = _t_head(b, i); n, i = _t_val(b, i, lt)
        m = {}
        for _ in range(n):
            _, kt, i = _t_head(b, i); k, i = _t_val(b, i, kt)
            _, vt, i = _t_head(b, i); v, i = _t_val(b, i, vt)
            m[k] = v
        return m, i
    if t == 9:
        _, lt, i = _t_head(b, i); n, i = _t_val(b, i, lt)
        out = []
        for _ in range(n):
            _, et, i = _t_head(b, i); v, i = _t_val(b, i, et); out.append(v)
        return out, i
    if t == 10:
        return tars_read(b, i)
    if t == 12:
        return 0, i
    if t == 13:
        _, _, i = _t_head(b, i)
        _, lt, i = _t_head(b, i); n, i = _t_val(b, i, lt)
        return bytes(b[i:i + n]), i + n
    raise ValueError(f'tars type {t}')


def tars_read(b, i=0):
    out = {}
    while i < len(b):
        tag, t, i = _t_head(b, i)
        if t == 11:
            return out, i
        v, i = _t_val(b, i, t)
        out[tag] = v
    return out, i


class Source:
    """一个其他平台直播间的连接：断了就等一会儿重连，一直跑到被取消"""

    def __init__(self, hub, plat, room, log):
        self.hub, self.plat, self.room, self.log = hub, plat, room, log
        self.label = PLATS[plat][0]
        self.state = '连接中'
        self.gift_names = {}

    def dm(self, uid, name, face, text, medal='', level=0):
        self.hub.danmaku(puid(self.plat, uid), str(name)[:40] or self.label + '观众', face, str(text)[:200], medal=str(medal)[:20], medal_level=min(int(level or 0), 1000),
                         plat=self.plat)

    def gift(self, uid, name, face, gift, num, yuan=0.0, img=''):
        self.hub.gift(puid(self.plat, uid), str(name)[:40] or self.label + '观众', face, str(gift)[:40] or '礼物', max(1, min(int(num or 1), 10 ** 6)),
                      round(float(yuan or 0), 2), img, plat=self.plat)

    def enter(self, uid, name, face):
        self.hub.enter(puid(self.plat, uid), str(name)[:40] or self.label + '观众', face, 'enter', 0, plat=self.plat)

    async def run(self, session):
        delay = 3
        while True:
            try:
                self.state = '连接中'
                await self.connect(session)
                delay = 3
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.state = f'断了：{type(e).__name__}'
                self.log.info('%s %s 连接断了：%s', self.label, self.room, e)
            await asyncio.sleep(delay + random.random() * 2)
            delay = min(60, delay * 2)


class Douyu(Source):
    async def connect(self, session):
        async with session.get(f'https://www.douyu.com/betard/{self.room}', headers={'User-Agent': UA}, timeout=aiohttp.ClientTimeout(total=15)) as r:
            j = await r.json(content_type=None)
        real = int(((j or {}).get('room') or {}).get('room_id') or self.room)
        if not self.gift_names:
            try:
                async with session.get(f'https://gift.douyucdn.cn/api/gift/v3/web/list?rid={real}', headers={'User-Agent': UA},
                                       timeout=aiohttp.ClientTimeout(total=15)) as r:
                    gl = await r.json(content_type=None)
                for g in (((gl or {}).get('data') or {}).get('giftList') or []):
                    price = ((g.get('priceInfo') or {}).get('price') or 0) / 100  # 鱼翅，按分算（1 鱼翅 = 1 元）
                    pic = str((g.get('basicInfo') or {}).get('giftPic') or '')
                    if pic.startswith('/'):
                        pic = str(g.get('picUrlPrefix') or 'https://gfs-op.douyucdn.cn/dygift') + pic
                    self.gift_names[str(g.get('id'))] = (str(g.get('name') or ''), price, pic)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, AttributeError):
                pass
            try:  # 免费的道具（荧光棒这些）不在直播间礼物表里，另有一张表
                async with session.get('https://webconf.douyucdn.cn/resource/common/prop_gift_list/prop_gift_config.json', headers={'User-Agent': UA},
                                       timeout=aiohttp.ClientTimeout(total=15)) as r:
                    t = await r.text()
                props = json.loads(t[t.index('(') + 1:t.rindex(')')]).get('data') or {}
                for gid, g in props.items():
                    if str(gid) not in self.gift_names and isinstance(g, dict):
                        self.gift_names[str(gid)] = (str(g.get('name') or ''), 0.0, str(g.get('bimg') or ''))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, AttributeError):
                pass
        ctx = ssl.create_default_context()
        ctx.set_ciphers('DEFAULT@SECLEVEL=0')  # 斗鱼弹幕服务器的证书 / 加密套件比较老，默认设置握不上手
        async with session.ws_connect(f'wss://danmuproxy.douyu.com:{random.choice([8501, 8502, 8503, 8504, 8505, 8506])}/',
                                      headers={'Origin': 'https://www.douyu.com', 'User-Agent': UA}, ssl=ctx, heartbeat=None) as ws:
            await ws.send_bytes(_dy_pack(f'type@=loginreq/roomid@={real}/'))
            await ws.send_bytes(_dy_pack(f'type@=joingroup/rid@={real}/gid@=-9999/'))
            self.state = '已连接'
            buf, last = b'', time.time()
            while True:
                if time.time() - last > 40:
                    await ws.send_bytes(_dy_pack('type@=mrkl/'))
                    last = time.time()
                m = await ws.receive(timeout=50)
                if m.type != aiohttp.WSMsgType.BINARY:
                    raise ConnectionError(f'斗鱼关了连接（{m.type}）')
                buf += m.data
                while len(buf) >= 12:
                    n = struct.unpack('<i', buf[:4])[0]
                    if n < 8 or n > 1 << 20:
                        raise ConnectionError('斗鱼数据不对')
                    if len(buf) < n + 4:
                        break
                    body, buf = buf[12:n + 4].rstrip(b'\0').decode('utf-8', 'replace'), buf[n + 4:]
                    self.handle(_dy_parse(body))

    def handle(self, d):
        t, ic = d.get('type'), d.get('ic', '')
        face = f'https://apic.douyucdn.cn/upload/{ic}_middle.jpg' if ic and re.fullmatch(r'[\w/.-]{3,200}', ic) else ''
        if t == 'chatmsg':
            self.dm(d.get('uid'), d.get('nn', ''), face, d.get('txt', ''), d.get('bnn', ''), d.get('bl') or 0)
        elif t == 'dgb':
            name, price, pic = self.gift_names.get(str(d.get('gfid')), ('', 0, ''))
            if not name and str(d.get('gfid') or '0') == '0':
                return  # 没有礼物编号的（活动之类），不当礼物记
            num = int(d.get('gfcnt') or 1)
            self.gift(d.get('uid'), d.get('nn', ''), face, name or f'礼物 {d.get("gfid")}', num, price * num, pic if pic.startswith('http') else '')
        elif t == 'uenter':
            self.enter(d.get('uid'), d.get('nn', ''), face)


class Huya(Source):
    async def connect(self, session):
        async with session.get(f'https://m.huya.com/{self.room}', headers={'User-Agent': UA_M}, timeout=aiohttp.ClientTimeout(total=15)) as r:
            page = await r.text()
        pu = re.search(r'"lPresenterUid":(\d+)', page)
        yy = re.search(r'"lYyid":(\d+)', page)
        if not pu:
            raise ConnectionError('虎牙房间号不对或者页面改了')
        groups = [f'live:{pu.group(1)}', f'chat:{pu.group(1)}'] + ([f'live:{yy.group(1)}', f'chat:{yy.group(1)}'] if yy and yy.group(1) != '0' else [])
        async with session.ws_connect('wss://cdnws.api.huya.com/', headers={'Origin': 'https://m.huya.com', 'User-Agent': UA_M}, heartbeat=None) as ws:
            req = _TW().strlist(0, groups).str(1, '')
            await ws.send_bytes(bytes(_TW().int(0, 16).bytes(1, bytes(req.b)).b))
            self.state = '已连接'
            last = time.time()
            while True:
                if time.time() - last > 50:  # 心跳：空的 WebSocketCommand（类型 1）
                    await ws.send_bytes(bytes(_TW().int(0, 1).b))
                    last = time.time()
                m = await ws.receive(timeout=60)
                if m.type != aiohttp.WSMsgType.BINARY:
                    raise ConnectionError(f'虎牙关了连接（{m.type}）')
                try:
                    d, _ = tars_read(m.data)
                    if d.get(0) == 7:
                        p, _ = tars_read(d.get(1, b''))
                        self.handle(p.get(1), p.get(2, b''))
                    elif d.get(0) == 22:
                        p, _ = tars_read(d.get(1, b''))
                        for it in p.get(1) or []:
                            self.handle(it.get(0), it.get(1, b''))
                except (ValueError, IndexError, struct.error, AttributeError):
                    continue

    def handle(self, uri, data):
        if uri not in (1400, 6501, 6502, 6110):
            return
        b, _ = tars_read(data)
        if uri == 1400:  # 弹幕
            u = b.get(0) or {}
            self.dm(u.get(0), u.get(2, ''), u.get(4, ''), b.get(3, ''))
        elif uri in (6501, 6502):  # 礼物
            self.gift(b.get(4), b.get(6, ''), b.get(14, ''), b.get(20, '') or '礼物', b.get(2) or 1)
        elif uri == 6110:  # 贵宾进房
            self.enter(b.get(0), b.get(1, ''), b.get(6, ''))


CLASSES = {'douyu': Douyu, 'huya': Huya}


class Platforms:
    """管其他平台的连接：设置变了就停掉旧的、开新的"""

    def __init__(self, hub, data_dir, persist, write_json, log, session_factory):
        self.hub, self.log, self.write_json = hub, log, write_json
        self.file = os.path.join(data_dir, 'platforms.json') if persist else None
        self.rooms, self.tasks, self.sources = [], {}, {}
        self.session_factory = session_factory
        try:
            with open(self.file, encoding='utf-8') as f:
                self.rooms = clean_rooms(json.load(f).get('rooms') or [])
        except (OSError, TypeError, ValueError, AttributeError):
            pass

    def view(self):
        out = []
        for r in self.rooms:
            src = self.sources.get((r['plat'], r['room']))
            out.append({**r, 'label': PLATS[r['plat']][0], 'state': src.state if (src and r['on']) else '没开'})
        return {'rooms': out}

    def set_rooms(self, rows):
        self.rooms = clean_rooms(rows)
        if self.file:
            self.write_json(self.file, {'rooms': self.rooms})
        self.apply()

    def apply(self):
        want = {(r['plat'], r['room']) for r in self.rooms if r['on']}
        for k in list(self.tasks):
            if k not in want:
                self.tasks.pop(k).cancel()
                self.sources.pop(k, None)
        for k in want:
            if k not in self.tasks:
                src = CLASSES[k[0]](self.hub, k[0], k[1], self.log)
                self.sources[k] = src
                self.tasks[k] = asyncio.get_event_loop().create_task(src.run(self.session_factory()))
