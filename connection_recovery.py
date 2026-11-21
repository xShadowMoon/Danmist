"""记录连接缺口；只补有稳定 SC 编号的数据，不用榜单差额猜收入。"""
import asyncio
import collections
import logging
import math
import time

import aiohttp
from error_journal import redact

log = logging.getLogger('xiaowu')
MAX_OUTAGES = 200


def retry_delay(retry_count, total=0):
    return min(60, 5 * 2 ** min(max(0, retry_count - 1), 4))


class RepeatFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.seen = collections.OrderedDict()

    def filter(self, record):
        if record.levelno < logging.WARNING:
            return True
        key = (record.name, record.lineno, redact(str(record.msg)))
        now = time.monotonic()
        if key in self.seen and now - self.seen[key] < 60:
            return False
        self.seen[key] = now
        self.seen.move_to_end(key)
        while len(self.seen) > 256:
            self.seen.popitem(last=False)
        return True


def connection_state(hub, ok, now=None):
    now = int(time.time() if now is None else now)
    s = hub.state
    if s.room.get('bili_ok') is ok:
        return False
    gap = s.outages[-1] if s.outages and s.outages[-1].get('up_at') is None else None
    if not ok:
        if gap is None:
            gap = {'down_at': max(int(s.session_start), min(now, int(hub.bili_seen))), 'up_at': None}
            s.outages.append(gap)
            del s.outages[:-MAX_OUTAGES]
        hub.room_update(bili_ok=False, down_at=gap['down_at'])
    elif gap:
        gap['up_at'] = max(now, gap['down_at'])
        gap['recovery'] = '待核对'
        hub.room_update(bili_ok=True, down_at=gap['down_at'], up_at=gap['up_at'])
        hub.wake.set()
        hub.guard_recovery = True
        hub.guard_wake.set()
        hub.recover_wake.set()
    else:
        hub.room_update(bili_ok=True)
    s.dirty = True
    return True


def counter(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10**15


def apply_recovery(hub, data, gap):
    s = hub.state
    room = data.get('room_info')
    if not isinstance(room, dict) or room.get('room_id') != (s.room.get('room_real') or s.room_id):
        raise ValueError('恢复信息的房间不匹配')
    start = room.get('live_start_time')
    if not counter(start) or not s.live_start or int(start) != int(s.live_start):
        hub.wake.set()
        raise ValueError('直播场次已变化，等待房间刷新')
    values = {}
    for container, field, output in (('watched_show', 'num', 'watched'), ('like_info_v3', 'total_likes', 'likes')):
        value = data.get(container)
        if isinstance(value, dict) and counter(value.get(field)):
            values[output] = int(value[field])
    if values:
        hub.room_update(**values)
    sc_info = data.get('super_chat_info')
    if sc_info is None:
        sc_info = {}
    if not isinstance(sc_info, dict):
        raise ValueError('SC 恢复信息格式不对')
    rows = sc_info.get('message_list', [])
    if not isinstance(rows, list):
        raise ValueError('SC 恢复信息格式不对')
    added = 0
    for row in rows[:5000]:
        try:
            user = row['user_info']
            sid, uid, price, sent, end = row['id'], row['uid'], row['price'], row['start_time'], row['end_time']
            if (isinstance(sid, bool) or not isinstance(sid, (int, str)) or not str(sid).isascii() or not str(sid).isdigit()
                    or len(str(sid)) > 30 or int(sid) <= 0 or type(uid) is not int or uid <= 0
                    or not counter(price) or price <= 0 or not counter(sent) or not counter(end) or end <= sent
                    or not isinstance(user, dict) or not isinstance(user.get('uname'), str) or len(user['uname']) > 64
                    or not isinstance(user.get('face', ''), str) or len(user.get('face', '')) > 2048
                    or not isinstance(row.get('message'), str) or len(row['message']) > 500):
                raise ValueError('SC 条目无效')
            if not max(s.session_start, s.live_start, gap['down_at']) <= sent <= gap['up_at']:
                continue
            if any(str(item['id']) == str(sid) for item in s.scs):
                continue
            guard = user.get('guard_level', 0)
            if type(guard) is not int or not 0 <= guard <= 3:
                raise ValueError('SC 舰长等级无效')
            if hub.super_chat(sid, uid, user['uname'], user.get('face', ''), price, row['message'], guard, end,
                              recovered=True, start=int(sent)):
                added += 1
        except (KeyError, TypeError, ValueError):
            log.warning('跳过格式不对的 SC 补录条目')
    gap['recovery'] = '已核对可见 SC 与房间数字'
    gap['sc_added'] = gap.get('sc_added', 0) + added
    s.dirty = True
    return added


async def recover_once(hub, session):
    s = hub.state
    if not s.outages or s.outages[-1].get('up_at') is None:
        return
    gap, sid = s.outages[-1], s.archive_id
    room = s.room.get('room_real') or s.room_id
    async with session.get('https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom',
                           params={'room_id': room}, timeout=aiohttp.ClientTimeout(total=15)) as response:
        payload = await response.json(content_type=None)
        if response.status != 200 or not isinstance(payload, dict) or payload.get('code') != 0 or not isinstance(payload.get('data'), dict):
            raise ValueError('恢复查询未成功')
    if s.archive_id != sid or not s.outages or s.outages[-1] is not gap:
        return
    apply_recovery(hub, payload['data'], gap)


async def watch_recovery(hub, session):
    while True:
        await hub.recover_wake.wait()
        hub.recover_wake.clear()
        for attempt in range(3):
            try:
                await recover_once(hub, session)
                break
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as e:
                log.warning('断线补录暂未完成：%s', e)
                if attempt < 2:
                    await asyncio.sleep(30 * (attempt + 1))
