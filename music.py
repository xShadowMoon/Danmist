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
import uuid

import aiohttp

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
}


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
            if type(x) is not int or not 0 <= x <= (3600 if k == 'maxdur' else 100):
                raise ValueError(f'{k} 数字不对')
        else:
            allowed = {'mode': ('web', 'app'), 'src': ('163', 'qq'), 'skip': ('host', 'req', 'guard')}[k]
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

    def cookie(self):
        return (self.svc.logins.get('163') or {}).get('cookie', '')

    async def get(self, path, params=None, cookie=None):
        h = {'User-Agent': UA, 'Referer': 'https://music.163.com/'}
        ck = self.cookie() if cookie is None else cookie
        if ck:
            h['Cookie'] = ck
        async with self.svc.session.get('https://music.163.com' + path, params=params, headers=h,
                                        timeout=aiohttp.ClientTimeout(total=12)) as r:
            return await r.json(content_type=None), r

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

    def login(self):
        return self.svc.logins.get('qq') or {}

    async def mu(self, req, comm=None, cookie=''):
        body = {'comm': comm or {'ct': 24, 'cv': 0, 'format': 'json'}, 'req': req}
        h = {'User-Agent': UA, 'Referer': 'https://y.qq.com/', 'Content-Type': 'application/json'}
        if cookie:
            h['Cookie'] = cookie
        async with self.svc.session.post('https://u.y.qq.com/cgi-bin/musicu.fcg', data=json.dumps(body), headers=h,
                                         timeout=aiohttp.ClientTimeout(total=12)) as r:
            return (await r.json(content_type=None) or {}).get('req') or {}

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
        raise OSError('QQ 音乐客户端不能从外面点歌，用「网页放」')


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
        self.providers = {'163': NetEase(self), 'qq': QQMusic(self)}
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
        return {'on': self.rules['on'], 'mode': self.rules['mode'], 'now': time.time(),
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
        return ''

    async def request(self, d, text, own_room, followed):
        """观众点了一首。找不到、不合规则的也记一条（灰色，写原因），主播看得到"""
        why = self.check(d, own_room, followed)
        item = {'id': uuid.uuid4().hex[:12], 't': int(time.time()), 'uid': d['uid'], 'name': d['name'], 'face': d.get('face', ''),
                'guard': d.get('guard') or 0, 'src': self.rules['src'], 'sid': '', 'title': text, 'artist': '', 'dur': 0, 'cover': '',
                'state': 'deny' if why else ('wait' if self.rules['need_ok'] else 'ok')}
        if why:
            item['why'] = why
        else:
            try:
                song, miss = await self.find(text)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                self.log.warning('点歌搜不到（%s）：%s', text, e)
                song, miss = None, "音乐平台连不上或太频繁，过一会儿再点"
            if not song:
                item.update(state='deny', why=miss)
            else:
                item.update(song)
                if self.rules['maxdur'] and song['dur'] > self.rules['maxdur']:
                    item.update(state='deny', why=f'太长了（{song["dur"] // 60} 分钟）')
                elif any(x['sid'] == song['sid'] and x['state'] in ('wait', 'ok', 'play') for x in self.queue):
                    return  # 已经排着了，不重复
        self.queue.append(item)
        self.trim()
        self.push()
        self.wake.set()

    async def find(self, text):
        """找歌：「歌名」或者「歌名 - 歌手」。只要歌名对得上的（翻唱也算），按歌手对不对、能不能放挑第一首。
        找到了但都放不了（要登录或者会员）就回一个原因"""
        p = self.providers[self.rules['src']]
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
            if (self.rules['mode'] == 'app' and self.rules['src'] == '163') or await p.url(s['sid']):
                await p.detail(s)
                return s, ''
        return None, '要登录（或会员）才能放' if not self.logins.get(self.rules['src']) else '这首放不了（可能要会员）'

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
        self.wake.set()

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
                    if not nxt:
                        self.wake.clear()
                        await self.wake.wait()
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
