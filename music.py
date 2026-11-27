"""弹幕点歌直接放（2026-11-25）：观众发「点歌 歌名」，按主播定的规则排进队列，从网易云 / QQ 音乐找到歌直接放。

两种放法（主播自己选）：
- web：雾幕去音乐平台拿播放地址，由 OBS 的「放歌」浏览器源（/obs-music）或者开着「这页出声」的雾幕页面播放；
- app：叫电脑上的网易云音乐客户端放（orpheus:// 链接，只有 Windows 上装了网易云才行）。
服务器按每首歌的时长自己往下走，播放页只管放「现在该放的那首」，所以几个页面开着也不会乱。
登录信息（Cookie）只存在本机 data/music-login.json，不发给网页。
"""
import asyncio
import base64
import io
import json
import os
import random
import re
import sys
import time
import urllib.parse
import uuid

import aiohttp

from breaker import Breaker, Resting

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
QUEUE_MAX = 60
DEFAULTS = {
    'on': False,        # 开没开「直接放」
    'mode': 'web',      # web 网页放 / app 电脑上的网易云放
    'src': '163',       # 163 网易云 / qq QQ 音乐
    'need_ok': False,   # 要主播点同意才放
    'skip': 'host',     # 谁能发「切歌」：host 只有主播（在页面上点）/ req 点这首的人也能 / guard 舰长以上也能
    'max': 2,           # 每人同时排着几首（0 = 不限）
    'medal': 0,         # 粉丝牌 ≥ 几级（0 = 不看）
    'guard': 0,         # 0 谁都行 / 3 舰长及以上 / 2 提督及以上 / 1 只有总督
    'wealth': 0,        # 荣耀等级 ≥ 几级（0 = 不看）
    'follow': False,    # 要关注了主播（认粉丝牌：戴着本直播间的牌子，或者这场里点过关注）
    'maxdur': 420,      # 太长的歌不放（秒，0 = 不限）
    # 2026-11-26 点歌改版
    'reply': False,     # 自动回观众一句（已点 / 没找到 / 不合规则 / 已取消），用连直播间的号（或者机器人）发
    'idle': 'off',      # 没人点的时候：off 不放 / lib 从曲库里随机 / list 从网易云歌单里随机
    'idle_list': '',    # 网易云歌单的 id（粘链接也行，存的时候只留数字）
    'vol': 80,          # 放歌音量（0~100），网页放、OBS 放歌源都跟着它
    'fallback': True,   # 这个平台搜不到 / 只能试听：自动去另一个平台找（只在雾幕自己放时）
    'cd_user': 30,      # 同一个人隔几秒才能再点（0 = 不限）
    'cd_song': 10,      # 同一首歌放完几分钟内不再点（0 = 不限）
    'norm': True,       # 响度均衡：太响的压一点、太小的抬一点
    'bili': True,       # 能点 B 站视频（点歌 BV号）
}
OTHER = {'163': 'qq', 'qq': '163'}
SRC_WORDS = {'qq': 'qq', 'QQ': 'qq', 'qq音乐': 'qq', 'QQ音乐': 'qq', '网易': '163', '网易云': '163', 'wy': '163', '163': '163'}
BV_RE = re.compile(r'(BV[0-9A-Za-z]{10})|(?<![0-9A-Za-z])av(\d{1,12})|(b23\.tv/[0-9A-Za-z]{4,12})')
IDLE_NAME = '空闲时'
TITLE_SHORT = 10   # 自动回的那句话里歌名最多几个字（B 站弹幕 20 个字以内最稳）


def hash33(s):
    e = 0
    for c in s:
        e += (e << 5) + ord(c)
    return 2147483647 & e


def gtk(s):
    h = 5381
    for c in s:
        h += (h << 5) + ord(c)
    return h & 0x7fffffff


def clean_rules(c, old):
    out = dict(old)
    for k, v in DEFAULTS.items():
        if k not in c:
            continue
        x = c[k]
        if isinstance(v, bool):
            if type(x) is not bool:
                raise ValueError(f'{k} 只能是开或关')
        elif isinstance(v, int):
            if type(x) is not int or not 0 <= x <= {'maxdur': 3600, 'cd_user': 3600, 'cd_song': 1440}.get(k, 100):
                raise ValueError(f'{k} 数字不对')
        elif k == 'idle_list':
            if not isinstance(x, str) or len(x) > 300:
                raise ValueError('歌单链接不对')
            m = re.search(r'(?:[?&#]id=|playlist/)(\d{3,20})', x) or re.fullmatch(r'\s*(\d{3,20})\s*', x)
            if x.strip() and not m:
                raise ValueError('认不出歌单：粘网易云歌单的链接，或者歌单 id（一串数字）')
            x = m.group(1) if m else ''
        else:
            allowed = {'mode': ('web', 'app'), 'src': ('163', 'qq'), 'skip': ('host', 'req', 'guard'), 'idle': ('off', 'lib', 'list')}[k]
            if x not in allowed:
                raise ValueError(f'{k} 不支持')
        out[k] = x
    if out['guard'] not in (0, 1, 2, 3):
        raise ValueError('身份要求不对')
    return out


class NetEase:
    name = '网易云音乐'

    def __init__(self, svc):
        self.svc = svc
        self.breaker = Breaker('网易云音乐')  # 连着失败先歇一会（2026-11-26）

    def cookie(self):
        return (self.svc.logins.get('163') or {}).get('cookie', '')

    async def get(self, path, params=None, cookie=None):
        h = {'User-Agent': UA, 'Referer': 'https://music.163.com/'}
        ck = self.cookie() if cookie is None else cookie
        if ck:
            h['Cookie'] = ck
        self.breaker.check()
        try:
            async with self.svc.session.get('https://music.163.com' + path, params=params, headers=h,
                                            timeout=aiohttp.ClientTimeout(total=12)) as r:
                out = await r.json(content_type=None), r
        except (aiohttp.ClientError, asyncio.TimeoutError):
            self.breaker.fail()
            raise
        self.breaker.ok()
        return out

    async def search(self, q, n=8):
        j, _ = await self.get('/api/search/get', {'s': q, 'type': '1', 'limit': str(n)})
        if not isinstance(j, dict) or j.get('code') not in (200, None):
            raise ValueError(f'网易云搜歌没成功（{(j or {}).get("code") if isinstance(j, dict) else "?"}）')
        out = []
        for s in ((j or {}).get('result') or {}).get('songs') or []:
            out.append({'src': '163', 'sid': str(s.get('id')), 'title': str(s.get('name') or ''),
                        'artist': ' / '.join(str(a.get('name') or '') for a in s.get('artists') or []),
                        'dur': int((s.get('duration') or 0) / 1000), 'cover': ''})
        return out

    async def detail(self, song):
        try:
            j, _ = await self.get('/api/song/detail', {'ids': f'[{song["sid"]}]'})
            al = (((j or {}).get('songs') or [{}])[0].get('album') or {})
            pic = str(al.get('picUrl') or '')
            if pic.startswith('http'):
                song['cover'] = pic.replace('http://', 'https://') + '?param=200y200'
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, IndexError):
            pass

    async def lyric(self, sid):
        """这首的歌词（带时间轴的 LRC），OBS 歌词源用"""
        j, _ = await self.get('/api/song/lyric', {'id': sid, 'lv': '1', 'kv': '1', 'tv': '-1'})
        return str(((j or {}).get('lrc') or {}).get('lyric') or '')

    async def playlist(self, pid):
        """网易云歌单里的歌（空闲时随机放，2026-11-26）"""
        j, _ = await self.get('/api/playlist/detail', {'id': pid})
        pl = (j or {}).get('result') or (j or {}).get('playlist') or {}
        out = []
        for s in pl.get('tracks') or []:
            out.append({'src': '163', 'sid': str(s.get('id')), 'title': str(s.get('name') or ''),
                        'artist': ' / '.join(str(a.get('name') or '') for a in (s.get('artists') or s.get('ar') or [])),
                        'dur': int((s.get('duration') or s.get('dt') or 0) / 1000), 'cover': ''})
        return [s for s in out if s['sid'] and s['dur']]

    async def url(self, sid):
        j, _ = await self.get('/api/song/enhance/player/url', {'ids': f'[{sid}]', 'br': '320000'})
        d = ((j or {}).get('data') or [{}])[0]
        if d.get('freeTrialInfo'):  # 只能试听 30 秒的不算
            return ''
        return str(d.get('url') or '').replace('http://', 'https://')

    async def qr_start(self):
        j, _ = await self.get('/api/login/qrcode/unikey', {'type': '1'}, cookie='')
        key = str((j or {}).get('unikey') or '')
        if not key:
            raise ValueError('网易云没给二维码')
        # 2026-11-25 用户：扫了没反应。新版网易云 App 扫网页登录码要带 chainId，不然手机上确认了这边也收不到
        chain = f'v1_{uuid.uuid4().hex[:16]}_web_login_{int(time.time() * 1000)}'
        return key, {'svg': qr_svg(f'https://music.163.com/login?codekey={key}&chainId={chain}')}

    async def qr_poll(self, key):
        j, r = await self.get('/api/login/qrcode/client/login', {'key': key, 'type': '1'}, cookie='')
        code = (j or {}).get('code')
        if code not in (800, 801, 802):
            self.svc.log.info('网易云扫码登录：%s %s', code, str((j or {}).get('message') or '')[:60])
        if code == 803:
            got = {k: m.value for k, m in r.cookies.items()}
            for part in str((j or {}).get('cookie') or '').split(';'):  # 有的版本把登录信息放在返回的内容里
                k, _, v = part.strip().partition('=')
                if k in ('MUSIC_U', '__csrf', 'MUSIC_R_T') and v and k not in got:
                    got[k] = v
            ck = '; '.join(f'{k}={v}' for k, v in got.items() if k in ('MUSIC_U', '__csrf', 'NMTID', 'MUSIC_R_T'))
            if 'MUSIC_U=' not in ck:
                return 'fail', '登录成功了，但没拿到登录信息，再扫一次'
            name = ''
            try:
                a, _ = await self.get('/api/nuser/account/get', cookie=ck)
                name = str(((a or {}).get('profile') or {}).get('nickname') or '')
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                pass
            self.svc.save_login('163', {'cookie': ck, 'name': name or '网易云账号', 't': int(time.time())})
            return 'ok', f'网易云已登录：{name}' if name else '网易云已登录'
        known = {800: ('expired', '二维码过期了，换一张'), 801: ('wait', '用网易云音乐 App 扫码'),
                 802: ('scanned', '扫好了，在手机上点确认')}
        if code in known:
            return known[code]
        # 以前别的情况一律当「等扫码」，扫完一直没反应；现在把网易云说的原因显示出来
        return 'fail', f'网易云没让登录（{code} {str((j or {}).get("message") or "").strip()}），换一张再扫，或者等一会儿'

    def app_play(self, sid):
        """叫电脑上的网易云客户端放这首（网页版「在客户端打开」用的就是这个链接）"""
        payload = base64.b64encode(json.dumps({'type': 'song', 'id': str(sid), 'cmd': 'play'}).encode()).decode()
        if sys.platform != 'win32':
            raise OSError('只有 Windows 上能叫网易云客户端')
        os.startfile('orpheus://' + payload)  # noqa: S606 —— 只用来打开网易云自己的链接


class QQMusic:
    name = 'QQ 音乐'

    def __init__(self, svc):
        self.svc = svc
        self.breaker = Breaker('QQ 音乐')

    def login(self):
        return self.svc.logins.get('qq') or {}

    async def mu(self, req, comm=None, cookie=''):
        body = {'comm': comm or {'ct': 24, 'cv': 0, 'format': 'json'}, 'req': req}
        h = {'User-Agent': UA, 'Referer': 'https://y.qq.com/', 'Content-Type': 'application/json'}
        if cookie:
            h['Cookie'] = cookie
        self.breaker.check()
        try:
            async with self.svc.session.post('https://u.y.qq.com/cgi-bin/musicu.fcg', data=json.dumps(body), headers=h,
                                             timeout=aiohttp.ClientTimeout(total=12)) as r:
                out = (await r.json(content_type=None) or {}).get('req') or {}
        except (aiohttp.ClientError, asyncio.TimeoutError):
            self.breaker.fail()
            raise
        self.breaker.ok()
        return out

    async def search(self, q, n=8):
        d = await self.mu({'module': 'music.search.SearchCgiService', 'method': 'DoSearchForQQMusicDesktop',
                           'param': {'query': q, 'num_per_page': n, 'page_num': 1, 'search_type': 0}}, {'ct': 19, 'cv': 1859})
        out = []
        for s in (((d.get('data') or {}).get('body') or {}).get('song') or {}).get('list') or []:
            am = str((s.get('album') or {}).get('mid') or '')
            out.append({'src': 'qq', 'sid': str(s.get('mid') or ''), 'title': str(s.get('name') or s.get('title') or ''),
                        'artist': ' / '.join(str(a.get('name') or '') for a in s.get('singer') or []),
                        'dur': int(s.get('interval') or 0),
                        'cover': f'https://y.gtimg.cn/music/photo_new/T002R300x300M000{am}.jpg' if re.fullmatch(r'\w{6,20}', am) else ''})
        return out

    async def detail(self, song):
        return

    async def lyric(self, sid):
        h = {'User-Agent': UA, 'Referer': 'https://y.qq.com/'}
        async with self.svc.session.get('https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg',
                                        params={'songmid': sid, 'format': 'json', 'nobase64': '1', 'g_tk': '5381'}, headers=h,
                                        timeout=aiohttp.ClientTimeout(total=10)) as r:
            j = json.loads(re.sub(r'^[^{]*|[^}]*$', '', await r.text()) or '{}')
        return str(j.get('lyric') or '')

    async def url(self, sid):
        lg = self.login()
        uin, key = str(lg.get('uin') or '0'), lg.get('key', '')
        ck = f'uin={uin}; qqmusic_key={key}; qm_keyst={key}' if key else ''
        d = await self.mu({'module': 'vkey.GetVkeyServer', 'method': 'CgiGetVkey',
                           'param': {'guid': '1234567890', 'songmid': [sid], 'songtype': [0], 'uin': uin, 'loginflag': 1, 'platform': '20'}},
                          {'uin': uin, 'format': 'json', 'ct': 24, 'cv': 0}, ck)
        data = d.get('data') or {}
        purl = str(((data.get('midurlinfo') or [{}])[0]).get('purl') or '')
        if not purl:
            return ''
        sip = [x for x in data.get('sip') or [] if str(x).startswith('http')]
        return (sip[0] if sip else 'https://ws.stream.qqmusic.qq.com/').replace('http://', 'https://') + purl

    async def qr_start(self):
        """QQ 扫码：先拿 QQ 互联的二维码，扫完换成 QQ 音乐的登录信息（2026-11-25，按网页版 y.qq.com 的登录流程做的）"""
        jar = aiohttp.CookieJar(unsafe=True)
        sess = aiohttp.ClientSession(cookie_jar=jar, headers={'User-Agent': UA})
        try:
            async with sess.get('https://ssl.ptlogin2.qq.com/ptqrshow',
                                params={'appid': '716027609', 'e': '2', 'l': 'M', 's': '3', 'd': '72', 'v': '4', 't': str(random.random()),
                                        'daid': '383', 'pt_3rd_aid': '100497308'}, timeout=aiohttp.ClientTimeout(total=12)) as r:
                png = await r.read()
            qrsig = next((c.value for c in jar if c.key == 'qrsig'), '')
            if not qrsig or not png:
                raise ValueError('QQ 没给二维码')
        except Exception:
            await sess.close()
            raise
        key = uuid.uuid4().hex
        self.svc.qq_flows[key] = {'sess': sess, 'qrsig': qrsig, 't': time.time()}
        return key, {'png': 'data:image/png;base64,' + base64.b64encode(png).decode()}

    async def qr_poll(self, key):
        f = self.svc.qq_flows.get(key)
        if not f:
            return 'expired', '二维码过期了，换一张'
        sess = f['sess']
        params = {'u1': 'https://graph.qq.com/oauth2.0/login_jump', 'ptqrtoken': str(hash33(f['qrsig'])), 'ptredirect': '0', 'h': '1',
                  't': '1', 'g': '1', 'from_ui': '1', 'ptlang': '2052', 'action': f'0-0-{int(time.time() * 1000)}', 'js_ver': '20102616',
                  'js_type': '1', 'login_sig': '', 'pt_uistyle': '40', 'aid': '716027609', 'daid': '383', 'pt_3rd_aid': '100497308', 'has_onekey': '1'}
        async with sess.get('https://ssl.ptlogin2.qq.com/ptqrlogin', params=params, timeout=aiohttp.ClientTimeout(total=12)) as r:
            text = await r.text()
        m = re.search(r"ptuiCB\('(\d+)','\d+','([^']*)'", text)
        code = m.group(1) if m else ''
        if code == '66':
            return 'wait', '用手机 QQ 扫码'
        if code == '67':
            return 'scanned', '扫好了，在手机上点确认'
        if code != '0':
            msg = re.search(r"ptuiCB\('\d+','\d+','[^']*','[^']*','([^']*)'", text)
            self.svc.log.info('QQ 扫码登录：%s %s', code, msg.group(1) if msg else text[:80])
            self.svc.drop_flow(key)
            if code == '65':
                return 'expired', '二维码过期了，换一张'
            return 'fail', f'QQ 没让登录（{code} {msg.group(1) if msg else ""}），换一张再扫'
        try:
            async with sess.get(m.group(2), allow_redirects=False, timeout=aiohttp.ClientTimeout(total=12)):
                pass
            p_skey = next((c.value for c in sess.cookie_jar if c.key == 'p_skey'), '')
            if not p_skey:
                return 'fail', 'QQ 登录没拿到授权，再扫一次'
            g = gtk(p_skey)
            form = {'response_type': 'code', 'client_id': '100497308',
                    'redirect_uri': 'https://y.qq.com/portal/wx_redirect.html?login_type=1&surl=https://y.qq.com/',
                    'scope': 'get_user_info,get_app_friends', 'state': 'state', 'switch': '', 'from_ptlogin': '1', 'src': '1',
                    'update_auth': '1', 'openapi': '1010_1030', 'g_tk': str(g), 'auth_time': str(int(time.time() * 1000)),
                    'ui': str(uuid.uuid4()).upper()}
            async with sess.post('https://graph.qq.com/oauth2.0/authorize', data=form, allow_redirects=False,
                                 timeout=aiohttp.ClientTimeout(total=12)) as r:
                loc = r.headers.get('Location', '')
            cm = re.search(r'[?&]code=(\w+)', loc)
            if not cm:
                return 'fail', 'QQ 音乐没给登录码，再扫一次'
            d = await self.mu({'module': 'QQConnectLogin.LoginServer', 'method': 'QQLogin', 'param': {'code': cm.group(1)}},
                              {'g_tk': g, 'platform': 'yqq', 'ct': 24, 'cv': 0})
            data = d.get('data') or {}
            uin, mkey = str(data.get('musicid') or ''), str(data.get('musickey') or '')
            if not uin or not mkey:
                return 'fail', 'QQ 音乐登录没成功，再扫一次'
            self.svc.save_login('qq', {'uin': uin, 'key': mkey, 'name': f'QQ {uin[:3]}***{uin[-2:]}', 't': int(time.time())})
            return 'ok', 'QQ 音乐已登录'
        finally:
            if code == '0':
                self.svc.drop_flow(key)

    def app_play(self, sid):
        """叫电脑上的 QQ 音乐客户端放这首（2026-11-26 用户要的）：QQ 音乐自己的 qqmusic:// 链接，按歌的 mid 放。
        没装 QQ 音乐客户端的电脑会报错，那首记成放不了"""
        if sys.platform != 'win32':
            raise OSError('只有 Windows 上能叫 QQ 音乐客户端')
        p = json.dumps({'song': [{'type': '0', 'songmid': str(sid)}], 'action': 'play'}, separators=(',', ':'))
        try:
            os.startfile('qqmusic://qq.com/media/playSonglist?p=' + urllib.parse.quote(p, safe=''))  # noqa: S606 —— 只用来打开 QQ 音乐自己的链接
        except OSError:
            raise OSError('没找到 QQ 音乐客户端（要先装好、登录）')


class Bili:
    """点 B 站视频的声音（2026-11-26 用户要的，比如点主播自己的歌切）：「点歌 BV号」「点歌 av号」「点歌 b23.tv 短链」。
    只放声音，用 B 站自己给的音频流；要带 Referer，所以都经雾幕转一手（/api/music/stream）"""
    name = 'B 站'
    HEAD = {'User-Agent': UA, 'Referer': 'https://www.bilibili.com/'}

    def __init__(self, svc):
        self.svc = svc

    def head(self):
        """B 站不让没登录的程序查视频（会回 412）：用连直播间的那个号（设置 → 账号）的登录信息"""
        ck = self.svc.bili_cookie() if self.svc.bili_cookie else ''
        return dict(self.HEAD, Cookie=ck) if ck else dict(self.HEAD)

    async def resolve(self, text):
        """从弹幕里认出视频，回一首歌的样子（sid = bvid:cid）；认不出回 None"""
        m = BV_RE.search(text or '')
        if not m:
            return None
        bvid, aid, short = m.groups()
        if short:  # 短链：问一下跳到哪
            async with self.svc.session.get('https://' + short, headers=self.head(), allow_redirects=False,
                                            timeout=aiohttp.ClientTimeout(total=10)) as r:
                loc = r.headers.get('Location', '')
            m2 = BV_RE.search(loc)
            if not m2 or m2.group(3):
                return None
            bvid, aid = m2.group(1), m2.group(2)
        params = {'bvid': bvid} if bvid else {'aid': aid}
        p = re.search(r'(?:[?&]p=|\bp)(\d{1,3})', text)
        async with self.svc.session.get('https://api.bilibili.com/x/web-interface/view', params=params, headers=self.head(),
                                        timeout=aiohttp.ClientTimeout(total=10)) as r:
            j = await r.json(content_type=None)
        d = j.get('data') if isinstance(j, dict) else None
        if not d or j.get('code') != 0:
            return None
        pages = d.get('pages') or [{'cid': d.get('cid'), 'duration': d.get('duration'), 'part': ''}]
        pg = pages[min(len(pages), int(p.group(1))) - 1] if p and int(p.group(1)) >= 1 else pages[0]
        title = str(d.get('title') or '')
        if len(pages) > 1 and pg.get('part'):
            title = f'{title} · {pg["part"]}'
        pic = str(d.get('pic') or '').replace('http://', 'https://')
        return {'src': 'bili', 'sid': f'{d.get("bvid")}:{pg.get("cid")}', 'title': title[:80], 'artist': str((d.get('owner') or {}).get('name') or ''),
                'dur': int(pg.get('duration') or d.get('duration') or 0), 'cover': pic + '@200w_200h.jpg' if pic else ''}

    async def url(self, sid):
        bvid, _, cid = str(sid).partition(':')
        async with self.svc.session.get('https://api.bilibili.com/x/player/playurl', params={'bvid': bvid, 'cid': cid, 'fnval': '16', 'fourk': '0'},
                                        headers=self.head(), timeout=aiohttp.ClientTimeout(total=10)) as r:
            j = await r.json(content_type=None)
        audio = (((j or {}).get('data') or {}).get('dash') or {}).get('audio') or []
        if not audio:
            return ''
        best = max(audio, key=lambda a: a.get('bandwidth') or 0)
        return str(best.get('baseUrl') or best.get('base_url') or '')

    async def detail(self, song):
        return

    async def lyric(self, sid):
        return ''

    def app_play(self, sid):
        raise OSError('音乐客户端放不了 B 站视频')


def qr_svg(text):
    import qrcode
    import qrcode.image.svg
    buf = io.BytesIO()
    qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2).save(buf)
    return buf.getvalue().decode('utf-8')


class MusicService:
    def __init__(self, data_dir, persist, write_json, log, emit, emit_admin):
        self.file = os.path.join(data_dir, 'music.json') if persist else None
        self.login_file = os.path.join(data_dir, 'music-login.json') if persist else None
        self.write_json, self.log, self.emit, self.emit_admin = write_json, log, emit, emit_admin
        self.rules = dict(DEFAULTS)
        self.queue = []   # 排着的、正在放的、放完的（放完的留最近 20 首）
        self.logins = {}
        self.qq_flows = {}
        self.session = None
        self.wake = asyncio.Event()
        self.providers = {'163': NetEase(self), 'qq': QQMusic(self), 'bili': Bili(self)}
        self.last_req = {}       # 每个人上次点歌的时间（冷却）
        self.played = {}         # 每首歌上次放完的时间（同一首几分钟内不再点）
        self.lyric_cache = {}    # 歌词：{src:sid: 文字}
        self.say = None          # 自动回观众一句：async say(text, uid, dmid, name)，server.py 设
        self.idle_names = None   # 曲库里的歌名：() -> [(歌名, 歌手)]，server.py 设
        self.bili_cookie = None  # 连直播间那个号的登录信息（点 B 站视频要），server.py 设
        self.idle_recent = []    # 空闲时最近放过的，别老是那几首
        try:
            with open(self.file, encoding='utf-8') as f:
                j = json.load(f)
            self.rules = clean_rules(j.get('rules') or {}, DEFAULTS)
            self.queue = [x for x in j.get('queue') or [] if isinstance(x, dict) and x.get('state') in ('wait', 'ok', 'done')][-QUEUE_MAX:]
        except (OSError, TypeError, ValueError, AttributeError):
            pass
        try:
            with open(self.login_file, encoding='utf-8') as f:
                j = json.load(f)
            self.logins = {k: v for k, v in j.items() if k in ('163', 'qq') and isinstance(v, dict)}
        except (OSError, TypeError, ValueError, AttributeError):
            pass

    # ---------- 存盘、给网页的样子 ----------
    def save(self):
        if self.file:
            try:
                self.write_json(self.file, {'rules': self.rules, 'queue': [x for x in self.queue if x['state'] != 'play'][-QUEUE_MAX:]})
            except OSError as e:
                self.log.warning('点歌队列没存上：%s', e)

    def save_login(self, src, info):
        self.logins[src] = info
        if self.login_file:
            try:
                self.write_json(self.login_file, self.logins)
            except OSError as e:
                self.log.warning('音乐登录信息没存上：%s', e)
        self.emit_admin('music_rules', self.admin_view())

    def logout(self, src):
        self.logins.pop(src, None)
        if self.login_file:
            try:
                self.write_json(self.login_file, self.logins)
            except OSError:
                pass

    async def set_cookie(self, src, text):
        """「粘贴登录信息」（2026-11-25 用户扫码登不上）：在电脑浏览器登录网易云 / QQ 音乐网页版后，把 Cookie 粘进来。
        网易云只要 MUSIC_U；QQ 音乐要 uin 和 qqmusic_key（或 qm_keyst）。粘整段 Cookie 或者只粘 MUSIC_U 的值都行"""
        text = str(text or '').strip().strip('"\'')
        jar = {}
        for part in re.split(r';\s*', text):
            k, _, v = part.strip().partition('=')
            if k and v:
                jar[k.strip()] = v.strip()
        if src == '163':
            mu = jar.get('MUSIC_U') or (text if re.fullmatch(r'[0-9A-Fa-f]{60,}', text) else '')
            if not mu:
                return False, '没找到 MUSIC_U：粘整段 Cookie，或者只粘 MUSIC_U 后面那串'
            ck = f'MUSIC_U={mu}' + (f"; __csrf={jar['__csrf']}" if jar.get('__csrf') else '')
            a, _ = await self.providers['163'].get('/api/nuser/account/get', cookie=ck)
            name = str(((a or {}).get('profile') or {}).get('nickname') or '')
            if not name:
                return False, '这段登录信息网易云不认（可能过期了），在网页上重新登录再复制'
            self.save_login('163', {'cookie': ck, 'name': name, 't': int(time.time())})
            return True, f'网易云已登录：{name}'
        uin = re.sub(r'\D', '', jar.get('uin', '') or jar.get('qqmusic_uin', '') or jar.get('wxuin', ''))
        key = jar.get('qqmusic_key') or jar.get('qm_keyst') or ''
        if not uin or not key:
            return False, '没找到 uin 和 qqmusic_key：在 y.qq.com 登录后粘整段 Cookie'
        self.save_login('qq', {'uin': uin, 'key': key, 'name': f'QQ {uin[:3]}***{uin[-2:]}', 't': int(time.time())})
        return True, 'QQ 音乐已登录'

    def drop_flow(self, key):
        f = self.qq_flows.pop(key, None)
        if f:
            asyncio.get_event_loop().create_task(f['sess'].close())

    def admin_view(self):
        return {**self.rules, 'login': {k: v.get('name', '已登录') for k, v in self.logins.items()}}

    def view(self):
        """给所有人看的队列：不带播放地址的签名（地址每首放的时候再去拿）"""
        keep = ('id', 't', 'uid', 'name', 'face', 'guard', 'src', 'sid', 'title', 'artist', 'dur', 'cover', 'state', 'why', 'start')
        on = [x for x in self.queue if x['state'] in ('play', 'ok', 'wait', 'deny')]
        done = [x for x in self.queue if x['state'] in ('done', 'skip')][-5:]
        keep = keep + ('idle',)
        return {'on': self.rules['on'], 'mode': self.rules['mode'], 'now': time.time(), 'vol': self.rules['vol'], 'norm': self.rules['norm'],
                'list': [{k: x[k] for k in keep if k in x} for x in done + on]}

    def push(self):
        self.save()
        self.emit('music', self.view())

    def current(self):
        return next((x for x in self.queue if x['state'] == 'play'), None)

    # ---------- 弹幕来的 ----------
    def check(self, d, own_room, followed):
        R = self.rules
        g = d.get('guard') or 0
        if R['guard'] and not (g and g <= R['guard']):
            return {3: '要舰长以上', 2: '要提督以上', 1: '要总督'}[R['guard']]
        own_medal = (d.get('medal_level') or 0) if (not d.get('medal_room') or d.get('medal_room') == own_room) and d.get('medal') else 0
        if R['medal'] and not g and own_medal < R['medal']:
            return f'粉丝牌不到 {R["medal"]} 级'
        if R['wealth'] and (d.get('wealth') or 0) < R['wealth']:
            return f'荣耀等级不到 {R["wealth"]}'
        if R['follow'] and not g and not own_medal and not followed:
            return '要先关注主播'
        if R['max'] and sum(1 for x in self.queue if x['uid'] == d['uid'] and x['state'] in ('wait', 'ok', 'play')) >= R['max']:
            return f'每人最多排 {R["max"]} 首'
        left = int(self.last_req.get(d['uid'], 0) + R['cd_user'] - time.time()) if R['cd_user'] else 0
        if left > 0:
            return f'点太快了，{left} 秒后再点'
        return ''

    def reply(self, d, text):
        """自动回观众一句（开了「自动回一句」才回）"""
        if self.rules['reply'] and self.say and d.get('uid'):
            asyncio.get_event_loop().create_task(self.say(text, d.get('uid'), d.get('dmid', ''), d.get('name', '')))

    @staticmethod
    def short(title):
        title = str(title or '').strip()
        return title if len(title) <= TITLE_SHORT else title[:TITLE_SHORT - 1] + '…'

    def ahead(self, it):
        """前面还有几首（正在放的不算）"""
        n = 0
        for x in self.queue:
            if x is it:
                break
            if x['state'] in ('ok', 'wait') and not x.get('idle'):
                n += 1
        return n

    async def request(self, d, text, own_room, followed, host=False):
        """观众点了一首。找不到、不合规则的也记一条（灰色，写原因），主播看得到。host=True：主播自己在页面上加的，不看规则"""
        why = '' if host else self.check(d, own_room, followed)
        item = {'id': uuid.uuid4().hex[:12], 't': int(time.time()), 'uid': d['uid'], 'name': d['name'], 'face': d.get('face', ''),
                'guard': d.get('guard') or 0, 'src': self.rules['src'], 'sid': '', 'title': text, 'artist': '', 'dur': 0, 'cover': '',
                'state': 'deny' if why else ('wait' if self.rules['need_ok'] else 'ok')}
        if why:
            item['why'] = why
        else:
            if not host:
                self.last_req[d['uid']] = time.time()
            try:
                song, miss = await self.find(text)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                self.log.warning('点歌搜不到（%s）：%s', text, e)
                song, miss = None, "音乐平台连不上或太频繁，过一会儿再点"
            if not song:
                item.update(state='deny', why=miss)
            else:
                item.update(song)
                if host:
                    item['state'] = 'ok'
                if self.rules['maxdur'] and song['dur'] > self.rules['maxdur'] and not host:
                    item.update(state='deny', why=f'太长了（{song["dur"] // 60} 分钟）')
                elif any(x['sid'] == song['sid'] and x['state'] in ('wait', 'ok', 'play') and not x.get('idle') for x in self.queue):
                    self.reply(d, f'{self.short(song["title"])}已经在排了')
                    return  # 已经排着了，不重复
                elif not host and self.rules['cd_song'] and time.time() - self.played.get(song['sid'], 0) < self.rules['cd_song'] * 60:
                    item.update(state='deny', why=f'这首刚放过，{self.rules["cd_song"]} 分钟内不再点')
        cur = self.current()
        if cur and cur.get('idle') and item['state'] == 'ok':  # 空闲时随便放的那首让位给观众点的
            cur['state'] = 'done'
        self.queue.append(item)
        self.trim()
        self.push()
        self.wake.set()
        if not host:
            if item['state'] == 'deny':
                self.reply(d, f'{self.short(text)}：{item.get("why") or "点不了"}')
            elif item['state'] == 'wait':
                self.reply(d, f'已点{self.short(item["title"])}，等主播同意')
            else:
                n = self.ahead(item)
                self.reply(d, f'已点{self.short(item["title"])}' + (f'，前面还有{n}首' if n else '，马上放'))

    def cancel_by(self, d):
        """弹幕「取消点歌」：撤掉这个人最后点的、还没开始放的那首"""
        it = next((x for x in reversed(self.queue) if x['uid'] == d['uid'] and x['state'] in ('ok', 'wait')), None)
        if not it:
            self.reply(d, '你没有排着的歌')
            return False
        it['state'] = 'skip'
        it['why'] = '点歌的人取消了'
        self.push()
        self.wake.set()
        self.reply(d, f'已取消{self.short(it["title"])}')
        return True

    async def alternatives(self, iid):
        """放错版本时换一首：按这首的歌名再搜一次，列出能选的（存在这首身上，换的时候只认这里面的）"""
        it = next((x for x in self.queue if x['id'] == iid), None)
        if not it:
            raise ValueError('这首已经不在了')
        if it['src'] == 'bili':
            raise ValueError('B 站视频没有别的版本可换')
        p = self.providers[it['src']]
        q = it.get('ask') or it['title']
        songs = [s for s in await p.search(q, 12) if s['sid'] and s['dur']][:10]
        it['alts'] = {s['sid']: s for s in songs}
        return [{k: s[k] for k in ('sid', 'title', 'artist', 'dur')} for s in songs]

    async def swap(self, iid, sid):
        it = next((x for x in self.queue if x['id'] == iid), None)
        if not it or str(sid) not in (it.get('alts') or {}):
            raise ValueError('这首已经不在了，或者先点「换」再选')
        s = dict(it['alts'][str(sid)])
        p = self.providers[it['src']]
        if self.rules['mode'] != 'app' and not await p.url(s['sid']):
            raise ValueError('这个版本放不了（可能要会员）')
        await p.detail(s)
        it.setdefault('ask', it['title'])
        it.update({k: s[k] for k in ('sid', 'title', 'artist', 'dur', 'cover')})
        it.pop('why', None)
        if it['state'] == 'deny':
            it['state'] = 'ok'
        if it['state'] == 'play':  # 正在放的换了：从头放新的
            it['start'] = time.time() + 1.5
            if self.rules['mode'] == 'app':
                p.app_play(it['sid'])
        self.push()
        self.wake.set()
        return f'换成了：{s["title"]}' + (f' · {s["artist"]}' if s['artist'] else '')

    async def pick_idle(self):
        """没人点的时候放什么（2026-11-26）：曲库里随机 / 网易云歌单里随机。找不到就算了"""
        R = self.rules
        try:
            if R['idle'] == 'list' and R['idle_list']:
                pool = await self.providers['163'].playlist(R['idle_list'])
                pool = [s for s in pool if s['sid'] not in self.idle_recent] or pool
                random.shuffle(pool)
                p = self.providers['163']
                for s in pool[:6]:
                    if (R['mode'] == 'app') or await p.url(s['sid']):
                        await p.detail(s)
                        return s
            elif R['idle'] == 'lib' and self.idle_names:
                names = list(self.idle_names() or [])
                random.shuffle(names)
                for name, artist in names[:6]:
                    song, _ = await self.find(f'{name} - {artist}' if artist else name)
                    if song and song['sid'] not in self.idle_recent:
                        return song
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, Resting, KeyError) as e:
            self.log.info('空闲时找歌没成功：%s', e)
        return None

    async def find(self, text):
        """找歌：「歌名」「歌名 - 歌手」「qq 歌名」（指定平台）「BV号」（B 站视频）。
        这个平台搜不到、只能试听的，开了「自动换平台」就去另一个平台再找一次（2026-11-26）"""
        R = self.rules
        if BV_RE.search(text):
            if not R['bili']:
                return None, '没开点 B 站视频'
            if R['mode'] == 'app':
                return None, '用音乐客户端放时点不了 B 站视频'
            if not (self.bili_cookie and self.bili_cookie()):
                return None, '点视频要先登录 B 站号（设置 → 账号）'
            try:
                s = await self.providers['bili'].resolve(text)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                s = None
            if not s or not s['dur']:
                return None, '没找到这个视频'
            if not await self.providers['bili'].url(s['sid']):
                return None, '这个视频放不了'
            return s, ''
        m = re.match(r'\s*(qq音乐|QQ音乐|qq|QQ|网易云|网易|wy|163)\s*[:：]?\s+(.+)$', text)
        if m:
            src, text = SRC_WORDS[m.group(1)], m.group(2).strip()
            if R['mode'] == 'app' and src != R['src']:
                return None, f'现在只用{self.providers[R["src"]].name}客户端放'
            return await self.find_in(src, text)
        song, miss = await self.find_in(R['src'], text)
        if song or not R['fallback'] or R['mode'] == 'app':
            return song, miss
        song2, _ = await self.find_in(OTHER[R['src']], text)
        return (song2, '') if song2 else (None, miss)

    async def find_in(self, src, text):
        """在一个平台里找：只要歌名对得上的（翻唱也算），按歌手对不对、能不能放挑第一首。
        找到了但都放不了（要登录或者会员）就回一个原因"""
        p = self.providers[src]
        m = re.match(r'(.+?)\s*[-—–/]\s*(.+)', text)
        title, artist = (m.group(1).strip(), m.group(2).strip()) if m else (text.strip(), '')
        songs = await p.search(f'{title} {artist}'.strip(), 12)
        key = re.sub(r'\s+', '', title).lower()
        hits = [s for s in songs if s['sid'] and s['dur'] and key in re.sub(r'\s+', '', s['title']).lower()]
        if artist:
            hits.sort(key=lambda s: artist.lower() not in s['artist'].lower())
        if not hits:
            return None, '没找到这首'
        for s in hits[:5]:
            if self.rules['mode'] == 'app' or await p.url(s['sid']):  # 客户端放：用客户端自己的登录，这里不用拿地址
                await p.detail(s)
                return s, ''
        return None, '要登录（或会员）才能放' if not self.logins.get(src) else '这首放不了（可能要会员）'

    def trim(self):
        old = [x for x in self.queue if x['state'] in ('done', 'skip', 'deny')]
        if len(self.queue) > QUEUE_MAX and old:
            drop = set(id(x) for x in old[:len(self.queue) - QUEUE_MAX])
            self.queue = [x for x in self.queue if id(x) not in drop]

    def skip_by(self, d):
        """弹幕「切歌」：按规则看这个人能不能切"""
        cur = self.current()
        if not cur:
            return False
        R = self.rules
        ok = (R['skip'] == 'req' and cur['uid'] == d['uid']) or (R['skip'] == 'guard' and (d.get('guard') or 0) > 0)
        if ok:
            self.next('skip')
        return ok

    # ---------- 主播在页面上点的 ----------
    def command(self, c):
        cmd = c['cmd']
        if cmd == 'music_vol':
            self.rules['vol'] = max(0, min(100, int(c.get('vol') or 0)))
            self.push()
            return f'音量 {self.rules["vol"]}%'
        if cmd == 'music_rules':
            self.rules = clean_rules({k: v for k, v in c.items() if k in DEFAULTS}, self.rules)
            self.emit_admin('music_rules', self.admin_view())
            self.push()
            self.wake.set()
            return '设置已保存'
        if cmd == 'music_next':
            self.next('skip')
            return '切到下一首'
        it = next((x for x in self.queue if x['id'] == c.get('id')), None)
        if not it:
            return '这首已经不在了'
        if cmd == 'music_ok' and it['state'] in ('wait', 'deny') and it.get('sid'):
            it['state'] = 'ok'
            it.pop('why', None)
        elif cmd == 'music_del':
            if it['state'] == 'play':
                self.next('skip')
            it['state'] = 'skip'
        elif cmd == 'music_top' and it['state'] in ('ok', 'wait'):
            self.queue.remove(it)
            i = next((k + 1 for k, x in enumerate(self.queue) if x['state'] == 'play'), len([x for x in self.queue if x['state'] in ('done', 'skip')]))
            self.queue.insert(i, it)
        self.push()
        self.wake.set()
        return '点歌队列已更新'

    def next(self, how='done'):
        cur = self.current()
        if cur:
            cur['state'] = 'done' if how == 'done' else 'skip'
            self.played[cur.get('sid', '')] = time.time()
        self.wake.set()

    def move(self, iid, before):
        """拖动排序（2026-11-26）：把这首挪到 before 那首前面（before 空 = 挪到最后）。只在排着的歌之间挪"""
        it = next((x for x in self.queue if x['id'] == iid and x['state'] in ('ok', 'wait')), None)
        if not it:
            raise ValueError('这首已经不在了')
        self.queue.remove(it)
        tgt = next((k for k, x in enumerate(self.queue) if x['id'] == before), None) if before else None
        if tgt is None:
            self.queue.append(it)
        else:
            self.queue.insert(tgt, it)
        self.push()
        return '顺序改好了'

    async def lyrics_for(self, it):
        """正在放的这首的歌词（OBS 歌词源跟着点歌姬走），拿过的记下来"""
        if not it or not it.get('sid'):
            return ''
        k = f'{it["src"]}:{it["sid"]}'
        if k not in self.lyric_cache:
            try:
                self.lyric_cache[k] = (await self.providers[it['src']].lyric(it['sid']))[:20000]
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, AttributeError, Resting):
                return ''
            if len(self.lyric_cache) > 50:
                self.lyric_cache.pop(next(iter(self.lyric_cache)))
        return self.lyric_cache[k]

    # ---------- 往下放 ----------
    async def url_for(self, it):
        """播放页来要地址：现在这首才给（地址有时效，到点再拿）"""
        if not it or it['state'] != 'play':
            return ''
        return await self.providers[it['src']].url(it['sid'])

    async def run(self, session):
        self.session = session
        while True:
            try:
                cur = self.current()
                if not self.rules['on']:
                    if cur:
                        cur['state'] = 'ok'
                        cur.pop('start', None)
                        self.push()
                    self.wake.clear()
                    await self.wake.wait()
                    continue
                if not cur:
                    nxt = next((x for x in self.queue if x['state'] == 'ok'), None)
                    if not nxt and self.rules['idle'] != 'off':
                        s = await self.pick_idle()  # 没人点：放一首备用的
                        if s and not next((x for x in self.queue if x['state'] == 'ok'), None):
                            self.idle_recent = (self.idle_recent + [s['sid']])[-20:]
                            nxt = {'id': uuid.uuid4().hex[:12], 't': int(time.time()), 'uid': 0, 'name': IDLE_NAME, 'face': '', 'guard': 0,
                                   'state': 'ok', 'idle': True, **s}
                            self.queue.append(nxt)
                            self.trim()
                        else:
                            nxt = next((x for x in self.queue if x['state'] == 'ok'), None)
                    if not nxt:
                        self.wake.clear()
                        try:  # 开了空闲歌单但这次没找到：过一会儿再试
                            await asyncio.wait_for(self.wake.wait(), 60 if self.rules['idle'] != 'off' else None)
                        except asyncio.TimeoutError:
                            pass
                        continue
                    nxt['state'], nxt['start'] = 'play', time.time() + 1.5  # 给播放页一点时间拿地址
                    if self.rules['mode'] == 'app':
                        try:
                            self.providers[nxt['src']].app_play(nxt['sid'])
                        except OSError as e:
                            nxt.update(state='skip', why=str(e))
                            self.push()
                            continue
                    self.push()
                    cur = nxt
                left = cur['start'] + cur['dur'] + 1 - time.time()
                if left <= 0:
                    cur['state'] = 'done'
                    self.played[cur.get('sid', '')] = time.time()
                    self.push()
                    continue
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), left)
                except asyncio.TimeoutError:
                    pass
                c2 = self.current()
                if c2 is cur and time.time() >= cur['start'] + cur['dur'] + 1:
                    cur['state'] = 'done'
                    self.played[cur.get('sid', '')] = time.time()
                    self.push()
                elif c2 is not cur:
                    self.push()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # 别让一首歌的问题把整个点歌停了
                self.log.warning('放歌出错：%s', e)
                await asyncio.sleep(3)
            for k in [k for k, f in self.qq_flows.items() if time.time() - f['t'] > 300]:
                self.drop_flow(k)
