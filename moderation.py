"""按需查询禁言名单；解除只发一次，异常结果不当成功，也不落盘保存名单。"""
import asyncio
import copy
import hashlib
import json
import logging
import re
import time

import aiohttp
import input_validation as valid

log = logging.getLogger('xiaowu')
LIST_URL = 'https://api.live.bilibili.com/xlive/web-ucenter/v1/banned/GetSilentUserList'
UNMUTE_URL = 'https://api.live.bilibili.com/banned_service/v1/Silent/del_room_block_user'
MUTE_URL = 'https://api.live.bilibili.com/xlive/web-ucenter/v1/banned/AddSilentUser'
NO_ADMIN = '机器人的号还不是这个直播间的房管：可以先在 B 站把它设成房管，或者扫码登录主播/房管自己的号再禁言'


class MuteQuery:
    def __init__(self):
        self.last_query = float('-inf')
        self.fetched = 0
        self.room = None
        self.account = ''
        self.rows = []

    def allow(self, now=None):
        now = time.monotonic() if now is None else now
        if now - self.last_query < 5:
            return False
        self.last_query = now
        return True


class MuteService:
    def __init__(self, hub, http, room_id, cookie_reader, demo=False):
        self.hub, self.http, self.room_id, self.cookie_reader, self.demo = hub, http, room_id, cookie_reader, demo
        self.demo_rows = [
            {'id': '101', 'uid': 90001, 'name': '演示观众一', 'until': None, 'until_text': '到本场结束', 'scope': 'session'},
            {'id': '102', 'uid': 90002, 'name': '演示观众二', 'until': None, 'until_text': '长期禁言', 'scope': 'permanent'},
        ]

    def credentials(self, acct):
        if acct:
            cookie, who = acct.get('cookie', ''), f"{acct.get('uname')} 的号"
            actor = acct.get('uid', 0)
        else:
            if not self.hub.state.room.get('bot_admin'):
                raise ValueError(NO_ADMIN)
            cookie, who = self.cookie_reader(), '机器人的号'
            match = re.search(r'DedeUserID=(\d+)', cookie or '')
            actor = int(match.group(1)) if match else 0
        match = re.search(r'bili_jct=([^;]+)', cookie)
        if not match:
            raise ValueError(f'{who}没登录')
        room = self.hub.state.room.get('room_real') or self.room_id
        return cookie, who, actor, match.group(1), room

    async def request(self, url, data, cookie):
        async with self.http.post(url, data=data, headers={'Cookie': cookie, 'Origin': 'https://live.bilibili.com',
                                  'Referer': f'https://live.bilibili.com/{self.room_id}'},
                                  timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False) as response:
            # 不信 Content-Length，流式检查实际大小，异常上游不能占满内存。
            body = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > 1024 * 1024:
                    raise ValueError('B 站返回格式不对，请稍后重查')
            if response.status != 200:
                raise ValueError('B 站暂时没返回结果，请稍后重查')
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError, RecursionError):
                raise ValueError('B 站返回格式不对，请稍后重查') from None
        if not isinstance(payload, dict) or type(payload.get('code')) is not int:
            raise ValueError('B 站返回格式不对，请稍后重查')
        valid.integer(payload['code'], 'B 站返回代码', -(2**31), 2**31-1)
        if payload['code'] != 0:
            raise ValueError(f"B 站没同意（{payload['code']}），请确认登录账号和房管权限")
        if 'data' not in payload:
            raise ValueError('B 站返回格式不对，请稍后重查')
        return payload['data']

    def changed(self, action, row):
        self.hub.emit_admin('mutes', {'refresh': True, 'action': action, 'uid': row['uid'],
                                     'name': row['name'], 'id': row.get('id')})

    async def listing(self, query, acct=None):
        if not query.allow():
            return False, '查得太快，请 5 秒后再查', {}
        query.rows = []
        if self.demo:
            query.rows = copy.deepcopy(self.demo_rows)
            query.fetched, query.account, query.room = time.monotonic(), 'demo', self.room_id
            return True, '已查到禁言名单', {'mutes': {'items': copy.deepcopy(query.rows), 'total': len(query.rows), 'truncated': False, 'skipped': 0}}
        try:
            cookie, who, actor, csrf, room = self.credentials(acct)
            rows, seen, count, skipped = [], set(), 0, 0
            total, pages = None, None
            # 整次分页也限 15 秒；任意一页坏了，就不给前几页冒充完整名单。
            async with asyncio.timeout(15):
                for page in range(1, 21):
                    data = await self.request(LIST_URL, {'room_id': str(room), 'pn': str(page), 'ps': '10',
                                                        'csrf': csrf, 'csrf_token': csrf}, cookie)
                    if not isinstance(data, dict) or not isinstance(data.get('data'), list) or len(data['data']) > 200:
                        raise ValueError('B 站返回的名单不完整，请稍后重查')
                    current_total = valid.integer(data.get('total'), '禁言人数', 0, 10**6)
                    current_pages = valid.integer(data.get('total_page', 1), '禁言页数', 0, 10**6)
                    current_pages = max(1, current_pages)
                    if total is None:
                        total, pages = current_total, current_pages
                    elif (current_total, current_pages) != (total, pages):
                        raise ValueError('禁言名单有变化，请重新查询')
                    if 'pn' in data and valid.integer(data['pn'], '页码', 1, 10**6) != page:
                        raise ValueError('B 站返回的页码不对，请稍后重查')
                    if 'ps' in data:
                        valid.integer(data['ps'], '每页人数', 1, 200)
                    if (total == 0 and data['data']) or (total > 0 and not data['data']) or page > pages:
                        raise ValueError('B 站返回的名单不完整，请稍后重查')
                    for raw in data['data']:
                        count += 1
                        try:
                            row = valid.mute_row(raw)
                        except (ValueError, TypeError, KeyError):
                            skipped += 1
                            log.warning('跳过格式不对的禁言条目')
                            continue
                        if row['id'] in seen:
                            raise ValueError('B 站返回了重复的禁言页，请稍后重查')
                        seen.add(row['id'])
                        if len(rows) < 200:
                            rows.append(row)
                    if count > total:
                        raise ValueError('B 站返回的名单人数不对，请稍后重查')
                    if page == pages:
                        if count != total:
                            raise ValueError('B 站返回的名单不完整，请稍后重查')
                        break
                    if count >= 200:
                        break
            query.rows, query.fetched = rows, time.monotonic()
            query.account, query.room = hashlib.sha256(cookie.encode()).hexdigest(), room
            note = f'已查到名单，跳过 {skipped} 条格式不对的记录' if skipped else '已查到禁言名单'
            return True, note, {'mutes': {'items': copy.deepcopy(rows), 'total': total,
                                                   'truncated': count < total, 'skipped': skipped}}
        except ValueError as e:
            return False, str(e), {}
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False, '连不上 B 站，稍后再试', {}

    async def unmute(self, query, record_id, acct=None):
        record_id = valid.mute_id(record_id)
        if self.demo:
            row = next((r for r in self.demo_rows if r['id'] == record_id), None)
            if row is None:
                return False, '这条禁言已不在名单里，请刷新'
            self.demo_rows.remove(row)
            self.changed('unmute', row)
            log.info('演示解除禁言：%s（%s），不发送请求', row['name'], row['uid'])
            return True, f"演示：已解除 {row['name']} 的禁言"
        try:
            cookie, who, actor, csrf, room = self.credentials(acct)
            row = next((r for r in query.rows if r['id'] == record_id), None)
            if (row is None or query.room != room or time.monotonic() - query.fetched > 300
                    or query.account != hashlib.sha256(cookie.encode()).hexdigest()):
                return False, '请先用当前账号刷新禁言名单'
            data = await self.request(UNMUTE_URL, {'roomid': str(room), 'id': record_id,
                                                 'csrf': csrf, 'csrf_token': csrf}, cookie)
            if data not in ({}, []):
                return False, 'B 站返回格式不对，请刷新名单确认结果'
            query.rows = [r for r in query.rows if r['id'] != record_id]
            log.info('从雾幕用%s（账号 %s）解除禁言：%s（%s），记录 %s', who, actor, row['name'], row['uid'], record_id)
            self.changed('unmute', row)
            return True, f"已用{who}解除 {row['name']} 的禁言"
        except ValueError as e:
            return False, str(e)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False, '解除结果未确认，请刷新名单后再操作'

    async def mute(self, uid, name, acct=None):
        if self.demo:
            return False, '演示模式不连接真实直播间或账号'
        if not uid:
            return False, '不知道这个人的 UID'
        try:
            cookie, who, actor, csrf, room = self.credentials(acct)
            # hour=0 + type=2 = 只禁言到这场直播结束（hour=-1 是永久，不用）
            data = {'room_id': str(room), 'tuid': str(uid), 'mobile_app': 'web',
                    'type': '2', 'hour': '0', 'csrf': csrf, 'csrf_token': csrf}
            result = await self.request(MUTE_URL, data, cookie)
            if not isinstance(result, dict) and result != []:
                return False, 'B 站返回格式不对，请刷新名单确认结果'
            log.info('从雾幕用%s禁言了 %s（%s）', who, name, uid)
            self.changed('mute', {'uid': uid, 'name': name})
            return True, f'已用{who}禁言 {name}（到这场直播结束）'
        except ValueError as e:
            return False, str(e)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False, '连不上 B 站，稍后再试'
