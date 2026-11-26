"""其他直播平台（2026-11-25）：斗鱼、虎牙的弹幕、礼物、进房，只读，跟 B 站的混在一起显示，每条标上平台。
抖音（2026-11-26）：不碰它的接口和签名，在这台电脑上开一个屏幕外的浏览器窗口正常打开直播间，从页面上读（见 Douyin）。

用法：设置 → 弹幕 → 「其他平台」里加直播间（同时在好几个平台开播时用）。存在 data/platforms.json。
每个直播间一个连接，断了自动重连；平台改了协议就只是这一路收不到，不影响 B 站。
uid 加上平台号 × 10^14，跟 B 站的 uid 不会撞。
"""
import asyncio
import hashlib
import json
import os
import random
import re
import ssl
import struct
import subprocess
import time

import aiohttp

PLATS = {'douyu': ('斗鱼', 1), 'huya': ('虎牙', 2), 'douyin': ('抖音', 3)}
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


# ---------- 抖音（2026-11-26）：不碰抖音的接口和签名。在这台电脑上开一个放在屏幕外面的普通浏览器窗口，
# 像人一样打开直播间网页，把页面上显示出来的弹幕、礼物、进房读出来。要登录 / 过验证时点「显示窗口」把它叫出来自己弄。
# 只在 Windows、装了 Edge 或 Chrome 的电脑上能用（桌面版就是这样）。登录状态存在 data/douyin-browser 里，下次还在。
DY_JS = r"""(() => {
  if (window.__danmistOn || window.top !== window) return;  // 只管直播间那一页，里面嵌的小页面不算
  window.__danmistOn = true;
  const send = o => { try { window.__danmist(JSON.stringify(o)); } catch (e) {} };
  // 列表是会重画的：同一个人 10 秒里同样的话只算一次
  const recent = new Map();
  const fresh = o => { const k = o.k + '|' + o.name + '|' + (o.text || o.gift || '') + '|' + (o.num || ''); const t = Date.now(); if (t - (recent.get(k) || 0) < 10000) return false; recent.set(k, t); if (recent.size > 500) recent.clear(); return true; };
  const seen = new Set(), seenEl = new WeakSet();  // 进房那种有 data-id，弹幕没有：按元素本身认
  // 一段内容里的字：文字原样，表情图用它的说明（[捂脸] 这种）
  const words = n => { let s = ''; n.childNodes.forEach(c => { s += c.nodeType === 3 ? c.textContent : c.tagName === 'IMG' ? (c.alt || '') : words(c); }); return s; };
  const level = it => { const m = it.innerHTML.match(/new_user_grade_level_v1_(\d+)/); return m ? +m[1] : 0; };
  const read = it => {
    const id = it.getAttribute('data-id') || '';
    if (seenEl.has(it) || (id && seen.has(id))) return;
    seenEl.add(it);
    if (id) seen.add(id);
    if (seen.size > 5000) seen.clear();
    // 一条：[等级、粉丝团小图] [名字：] [内容]，最后两个分别是名字和内容（类名是乱码，会变，不靠它）
    let row = it;
    while (row.children.length === 1) row = row.firstElementChild;  // 弹幕比进房多包一层
    const kids = [...row.children];
    if (kids.length < 2) return;
    const box = kids[kids.length - 1], name = kids[kids.length - 2].textContent.replace(/[：:]\s*$/, '').trim();
    const text = words(box).replace(/\s+/g, ' ').trim();
    if (!name || !text) return;
    const img = box.querySelector('img');
    const out = o => { if (fresh(o)) send(o); };
    let m;
    if (/^(来了|加入了直播间)$/.test(text)) out({ k: 'enter', name, lv: level(it) });
    else if (/^(为主播点赞了|分享了直播间|关注了主播|推荐直播给)/.test(text)) out({ k: 'act', name, text });
    else if ((m = text.match(/^送(?:出了?|给主播)\s*(?:\d+\s*个)?\s*(.+?)\s*[×xX]\s*(\d+)$/) || text.match(/^送(?:出了?|给主播)\s*(\d+)\s*个\s*(.+)$/)))
      out(/^\d+$/.test(m[1]) ? { k: 'gift', name, gift: m[2], num: +m[1], img: img ? img.src : '', lv: level(it) } : { k: 'gift', name, gift: m[1], num: +m[2], img: img ? img.src : '', lv: level(it) });
    else out({ k: 'dm', name, text, lv: level(it) });
  };
  const scan = n => { if (n.matches && n.matches('.webcast-chatroom___item')) read(n); if (n.querySelectorAll) n.querySelectorAll('.webcast-chatroom___item').forEach(read); };
  // 礼物价格：页面下面那排礼物写着「跑车 1200钻」
  const prices = () => {
    const p = {};
    document.querySelectorAll('[data-e2e="gifts-container"] *').forEach(e => { const m = (e.innerText || '').trim().match(/^([^\n]{1,20})\n(\d+)\s*钻$/); if (m) p[m[1].trim()] = +m[2]; });
    if (Object.keys(p).length) send({ k: 'prices', p });
  };
  const start = () => {
    document.querySelectorAll('.webcast-chatroom___item').forEach(it => { seenEl.add(it); const id = it.getAttribute('data-id'); if (id) seen.add(id); });  // 打开时已经在列表里的不算新的
    new MutationObserver(ms => { for (const m of ms) m.addedNodes.forEach(n => { if (n.nodeType === 1) scan(n); }); }).observe(document.documentElement, { childList: true, subtree: true });
    setTimeout(prices, 8000);
    setInterval(prices, 600000);
    send({ k: 'ready', url: location.href, title: document.title });
    // 每 10 秒报一次「还好不好」（2026-11-26）：弹出滑块验证、聊天区找不到了（抖音改版）都告诉雾幕，平台那行会亮黄字
    const shown = e => { if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 40 && r.height > 40 && getComputedStyle(e).visibility !== 'hidden'; };
    let born = Date.now();
    setInterval(() => {
      const verify = [...document.querySelectorAll('#captcha_container, .captcha_verify_container, [class*="captcha"], iframe[src*="verify"], iframe[src*="captcha"]')].some(shown);
      const chat = document.querySelector('.webcast-chatroom___item, [class*="webcast-chatroom___list"], [class*="webcast-chatroom___items"]');
      send({ k: 'health', s: verify ? 'verify' : chat ? 'ok' : (Date.now() - born > 30000 ? 'nodom' : 'wait') });
    }, 10000);
  };
  document.readyState === 'loading' ? addEventListener('DOMContentLoaded', start) : start();
})();"""


# 抖音直播视频流的地址（拉流域名都是 pull-xxx.douyincdn.com 这种，后缀 flv / m3u8 / ts）
VIDEO_URLS = ['*pull-*.douyincdn.com/*', '*pull-*.douyinliving.com/*', '*.flv?*', '*.flv', '*.m3u8*', '*.ts?*']


def find_browser():
    pf = [os.environ.get(k, '') for k in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA')]
    for base in pf:
        for rel in (r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe'):
            p = os.path.join(base, rel)
            if base and os.path.isfile(p):
                return p
    return None


def dy_uid(name):
    """网页上看不到抖音号，用名字算一个固定的数当 uid（同名的人会算成一个）"""
    return int(hashlib.md5(name.encode('utf-8')).hexdigest()[:12], 16)


class Douyin(Source):
    """抖音直播间：开一个屏幕外的浏览器窗口打开直播间网页，从页面上读（见上面）"""
    profile_root = ''  # data/ 文件夹，Platforms 设
    OFF = {'left': -32000, 'top': -32000, 'width': 1280, 'height': 860}
    ON = {'left': 80, 'top': 60, 'width': 1280, 'height': 860}

    alive = set()  # 正在用浏览器的抖音直播间（主直播间的「其他平台」和切过去看的共用一个浏览器）

    def __init__(self, hub, plat, room, log):
        super().__init__(hub, plat, room, log)
        Douyin.alive.add(self)
        self.proc = None
        self.ws = None
        self.calls = {}
        self.seq = 0
        self.window = None
        self.shown = False
        self.prices = {}
        self.warn = False  # 要人去看一眼（验证、页面改版）：平台那行亮黄字

    def profile(self):
        return os.path.join(self.profile_root or '.', 'douyin-browser')

    async def call(self, method, params=None, timeout=15):
        self.seq += 1
        fut = asyncio.get_event_loop().create_future()
        self.calls[self.seq] = fut
        await self.ws.send_str(json.dumps({'id': self.seq, 'method': method, 'params': params or {}}))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.calls.pop(self.seq, None)

    async def show(self, on):
        """把窗口拿到屏幕上（登录、过验证）或者放回屏幕外"""
        if not self.ws or self.window is None:
            return False
        try:
            await self.call('Browser.setWindowBounds', {'windowId': self.window, 'bounds': {'windowState': 'normal'}})
            await self.call('Browser.setWindowBounds', {'windowId': self.window, 'bounds': self.ON if on else self.OFF})
            self.shown = on
            if on:
                await self.call('Page.bringToFront')
            return True
        except Exception as e:
            self.log.info('抖音窗口挪不动：%s', e)
            return False

    async def devtools_port(self, session):
        """已经开着的（上次没关掉）就接着用；没有就开一个"""
        port_file = os.path.join(self.profile(), 'DevToolsActivePort')

        async def alive():
            try:
                with open(port_file, encoding='utf-8') as f:
                    port = int(f.readline().strip())
                async with session.get(f'http://127.0.0.1:{port}/json/version', timeout=aiohttp.ClientTimeout(total=3)) as r:
                    return port if r.status == 200 else 0
            except (OSError, ValueError, aiohttp.ClientError, asyncio.TimeoutError):
                return 0
        port = await alive()
        if port:
            return port
        exe = find_browser()
        if not exe:
            self.state = '没找到 Edge / Chrome，抖音要在装了浏览器的 Windows 电脑上用'
            raise RuntimeError('no browser')
        os.makedirs(self.profile(), exist_ok=True)
        try:
            os.remove(port_file)
        except OSError:
            pass
        args = [exe, '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1', '--remote-allow-origins=http://127.0.0.1', f'--user-data-dir={self.profile()}',
                '--no-first-run', '--no-default-browser-check', '--new-window', '--mute-audio',
                # 不装扩展、不登录同步：不然 Edge 会把电脑上的账号和你平时的扩展同步进来，扩展会弹窗（2026-11-26）
                '--disable-extensions', '--disable-sync', '--disable-features=msImplicitSignin',
                f"--window-position={self.OFF['left']},{self.OFF['top']}", f"--window-size={self.OFF['width']},{self.OFF['height']}",
                # 窗口在屏幕外也要照常刷新，不然页面不往下走
                '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows',
                f'https://live.douyin.com/{self.room}']
        flags = 0x08000000 if os.name == 'nt' else 0  # 不弹黑窗口
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        for _ in range(100):
            await asyncio.sleep(0.2)
            port = await alive()
            if port:
                return port
        raise RuntimeError('浏览器没开起来')

    async def connect(self, session):
        self.state = '打开直播间网页…'
        port = await self.devtools_port(session)
        url = f'https://live.douyin.com/{self.room}'
        async with session.get(f'http://127.0.0.1:{port}/json', timeout=aiohttp.ClientTimeout(total=5)) as r:
            targets = await r.json(content_type=None)
        page = next((t for t in targets if t.get('type') == 'page' and f'live.douyin.com/{self.room}' in t.get('url', '')), None)
        if not page:
            async with session.put(f'http://127.0.0.1:{port}/json/new?{url}', timeout=aiohttp.ClientTimeout(total=5)) as r:
                page = await r.json(content_type=None)
        async with session.ws_connect(page['webSocketDebuggerUrl'], max_msg_size=0) as ws:
            self.ws = ws
            reader = asyncio.get_event_loop().create_task(self.read(ws))
            try:
                await self.call('Runtime.enable')
                await self.call('Page.enable')
                await self.call('Runtime.addBinding', {'name': '__danmist'})
                # 只要弹幕，不要视频（2026-11-26）：直播视频流不让它下，省 CPU、显卡和网速；聊天走的是另一条连接，不受影响
                try:
                    await self.call('Network.enable')
                    await self.call('Network.setBlockedURLs', {'urls': VIDEO_URLS})
                except Exception as e:
                    self.log.info('抖音视频没拦住（不影响弹幕）：%s', e)
                await self.call('Page.addScriptToEvaluateOnNewDocument', {'source': DY_JS})
                await self.call('Runtime.evaluate', {'expression': DY_JS})
                try:
                    self.window = (await self.call('Browser.getWindowForTarget')).get('windowId')
                    if not self.shown:
                        await self.show(False)
                except Exception:
                    self.window = None
                self.state = '已打开，等弹幕'
                last_check = time.time()
                while not reader.done():
                    await asyncio.sleep(5)
                    if time.time() - last_check > 60:  # 每分钟看一眼还在不在直播间（被跳到登录 / 验证页时提示）
                        last_check = time.time()
                        r = await self.call('Runtime.evaluate', {'expression': 'location.href', 'returnByValue': True})
                        href = str(((r.get('result') or {}).get('value')) or '')
                        if f'live.douyin.com/{self.room}' not in href:
                            self.state, self.warn = '页面被跳走了（可能要登录或过验证）：点「显示窗口」看看', True
                reader.result()
            except asyncio.CancelledError:
                # 在设置里关掉 / 删掉这个直播间：只关自己这一页（同一个浏览器里可能还开着别的抖音直播间，2026-11-26）；
                # 最后一页关掉浏览器就自己退出了
                try:
                    await asyncio.wait_for(self.call('Page.close'), 3)
                except BaseException:
                    pass
                raise
            finally:
                reader.cancel()
                self.ws = None
                for f in self.calls.values():
                    if not f.done():
                        f.cancel()
                self.calls.clear()

    async def read(self, ws):
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                break
            m = json.loads(msg.data)
            if 'id' in m:
                f = self.calls.get(m['id'])
                if f and not f.done():
                    if 'error' in m:
                        f.set_exception(RuntimeError(str(m['error'].get('message'))))
                    else:
                        f.set_result(m.get('result') or {})
                continue
            meth = m.get('method')
            if meth == 'Runtime.bindingCalled' and (m.get('params') or {}).get('name') == '__danmist':
                try:
                    self.on_item(json.loads(m['params'].get('payload') or '{}'))
                except (ValueError, TypeError, KeyError) as e:
                    self.log.info('抖音一条没读懂：%s', e)
            elif meth in ('Inspector.detached', 'Inspector.targetCrashed'):
                raise RuntimeError('抖音页面关了')
        raise RuntimeError('抖音窗口关了')

    def on_item(self, d):
        k = d.get('k')
        name = str(d.get('name') or '')[:40]
        if k == 'ready':
            self.state = '已连接' if f'live.douyin.com/{self.room}' in str(d.get('url', '')) else '页面不对：点「显示窗口」看看'
        elif k == 'health':
            s = d.get('s')
            if s == 'verify':
                self.state, self.warn = '抖音要验证：点「显示窗口」过一下验证', True
            elif s == 'nodom':
                self.state, self.warn = '页面上找不到聊天区（可能没在直播或者抖音改版了）：点「显示窗口」看看', True
            elif s == 'ok' and self.warn:
                self.state, self.warn = '已连接', False
        elif k == 'prices' and isinstance(d.get('p'), dict):
            self.prices = {str(a)[:20]: int(b) for a, b in d['p'].items() if isinstance(b, (int, float))}
        elif not name:
            return
        elif k == 'dm':
            self.state = '已连接'
            self.dm(dy_uid(name), name, '', str(d.get('text') or ''))
        elif k == 'enter':
            self.enter(dy_uid(name), name, '')
        elif k == 'gift':
            gift = str(d.get('gift') or '礼物')[:20]
            num = max(1, min(int(d.get('num') or 1), 10 ** 6))
            diamonds = self.prices.get(gift, 0)
            img = str(d.get('img') or '')
            self.gift(dy_uid(name), name, '', gift, num, diamonds * num / 10, img if img.startswith('https://') else '')  # 1 钻 = 0.1 元

    async def run(self, session):
        try:
            await super().run(session)
        finally:
            self.close()

    def close(self):
        Douyin.alive.discard(self)
        if Douyin.alive:  # 还有别的抖音直播间在用这个浏览器
            return
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        self.proc = None


CLASSES = {'douyu': Douyu, 'huya': Huya, 'douyin': Douyin}


class Platforms:
    """管其他平台的连接：设置变了就停掉旧的、开新的"""

    def __init__(self, hub, data_dir, persist, write_json, log, session_factory):
        self.hub, self.log, self.write_json = hub, log, write_json
        self.file = os.path.join(data_dir, 'platforms.json') if persist else None
        self.rooms, self.tasks, self.sources = [], {}, {}
        self.session_factory = session_factory
        Douyin.profile_root = data_dir
        try:
            with open(self.file, encoding='utf-8') as f:
                self.rooms = clean_rooms(json.load(f).get('rooms') or [])
        except (OSError, TypeError, ValueError, AttributeError):
            pass

    def view(self):
        out = []
        for r in self.rooms:
            src = self.sources.get((r['plat'], r['room']))
            out.append({**r, 'label': PLATS[r['plat']][0], 'state': src.state if (src and r['on']) else '没开',
                        'warn': bool(src and r['on'] and getattr(src, 'warn', False))})
        # 抖音要在这台电脑上开浏览器：只有 Windows、装了 Edge / Chrome 才给选
        return {'rooms': out, 'douyin': os.name == 'nt' and bool(find_browser())}

    async def show(self, plat, room, on):
        """抖音：把那个浏览器窗口叫出来（登录、过验证），或者放回屏幕外"""
        src = self.sources.get((plat, str(room)))
        if not isinstance(src, Douyin):
            return False
        return await src.show(bool(on))

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
