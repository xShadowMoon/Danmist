"""B 站连接这一层（2026-11-26 从 server.py 搬出来，只搬家没改逻辑）：
blivedm 收到的消息怎么交给 Hub（Handler）、每分钟查一次直播间（poll_room）、切房时补最近的弹幕（backfill_side_room）、开播时间（live_ts）。"""
import aiohttp
import asyncio
import blivedm
import blivedm.models.web as web_models
import collections
import connection_recovery
import datetime
import json
import re
import time
import logging

log = logging.getLogger('danmaku')
BJ = datetime.timezone(datetime.timedelta(hours=8))


def live_ts(s):
    """B 站给的开播时间（北京时间字符串）转成时间戳，没开播是 0。"""
    try:
        return datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=BJ).timestamp()
    except (TypeError, ValueError):
        return 0


class TrackedClient(blivedm.BLiveClient):
    """使用现有库的关闭回调记录短断线，不必总等到 75 秒心跳超时。"""
    def __init__(self, hub, room_id, session):
        super().__init__(room_id, session=session)
        self.hub = hub

    async def _on_ws_close(self):
        await super()._on_ws_close()
        if not self.hub.stopping:
            connection_recovery.connection_state(self.hub, False)


class Handler(blivedm.BaseHandler):
    _CMD_CALLBACK_DICT = blivedm.BaseHandler._CMD_CALLBACK_DICT.copy()

    notice_logged = set()

    def __init__(self, hub):
        self.hub = hub
        self.seen = collections.deque(maxlen=500)  # 同一个礼物新旧两种协议可能各来一条，按 tid 去重

    def handle(self, client, command):
        self.hub.bili_message_seen = True
        self.hub.bili_seen = time.time()  # 包括每 30 秒的心跳，用来判断跟 B 站还连着没有
        if self.hub.state.room.get('bili_ok') is False or (self.hub.state.outages and self.hub.state.outages[-1].get('up_at') is None):
            connection_recovery.connection_state(self.hub, True, self.hub.bili_seen)
        try:
            if not isinstance(command, dict):
                raise ValueError('消息不是对象')
            cmd = str(command.get('cmd', '')).split(':')[0]
            # 没处理的 cmd 里带「活动 / 横幅」字样的，每种记一次原文到日志（2026-11-23：确认活动横幅是哪个 cmd，以后要加别的也好查）
            if cmd not in self._CMD_CALLBACK_DICT and cmd not in Handler.notice_logged and len(Handler.notice_logged) < 50:
                raw = json.dumps(command, ensure_ascii=False)
                if any(w in raw for w in ('查看活动', '活动', 'content_segments')):
                    Handler.notice_logged.add(cmd)
                    log.info('没处理的 B 站消息 %s：%s', cmd, raw[:600])
            super().handle(client, command)
        except (TypeError, ValueError, KeyError, AttributeError, IndexError, OverflowError):
            log.warning('跳过格式不对的 B 站消息')

    def __watched(self, client, command):
        d = command.get('data', {})
        self.hub.room_update(watched=d.get('num', 0), watched_text=d.get('text_large', ''))
    _CMD_CALLBACK_DICT['WATCHED_CHANGE'] = __watched  # noqa

    def __rank_count(self, client, command):
        d = command.get('data', {})
        n = d.get('online_count') or d.get('count') or 0
        self.hub.room_update(online=n)
    _CMD_CALLBACK_DICT['ONLINE_RANK_COUNT'] = __rank_count  # noqa

    def __like(self, client, command):
        self.hub.room_update(likes=command.get('data', {}).get('click_count', 0))
    _CMD_CALLBACK_DICT['LIKE_INFO_V3_UPDATE'] = __like  # noqa

    def __live(self, client, command):
        # 开播了：马上去查这场的开播时间，是新的一场就清零（在 poll_room 里判断）
        self.hub.room_update(live=1)
        self.hub.wake.set()
    _CMD_CALLBACK_DICT['LIVE'] = __live  # noqa

    def __preparing(self, client, command):
        # 下播：存一份这场的总结。数据先留着给主播看，下次开播再清零
        prev = self.hub.state.room.get('live')
        self.hub.room_update(live=0)
        if prev == 1:
            self.hub.close_broadcast('下播')
    _CMD_CALLBACK_DICT['PREPARING'] = __preparing  # noqa

    # B 站的活动 / 系统横幅（2026-11-23）：content_segments 是一段段字，拼起来；「查看活动>>」这种带链接的那段只留链接
    def __common_notice(self, client, command):
        d = command.get('data') or {}
        segs = d.get('content_segments') or []
        text, link = '', ''
        for sg in segs if isinstance(segs, list) else []:
            if not isinstance(sg, dict):
                continue
            t = str(sg.get('text') or '')
            u = str(sg.get('link') or sg.get('jump_url') or sg.get('url') or '')
            if u.startswith('http') and not link:
                link = u
                if '查看' in t:
                    continue
            text += t
        self.hub.room_notice(text, link)
    _CMD_CALLBACK_DICT['COMMON_NOTICE_DANMAKU'] = __common_notice  # noqa

    # 有人被禁言：B 站在直播间里发一条「xx 已被房管禁言」，雾幕也在弹幕里显示一条（2026-11-18）
    def __room_block(self, client, command):
        d = command.get('data') or {}
        uid = d.get('uid') or command.get('uid') or 0
        name = d.get('uname') or command.get('uname') or ''
        self.hub.room_block(int(uid or 0), str(name), d)
    _CMD_CALLBACK_DICT['ROOM_BLOCK_MSG'] = __room_block  # noqa

    # 舰长（和高荣耀等级的人）进房的特效消息，用来知道进来的是不是舰长
    # 2026-11-19 跟 B 站一样的几件事：点赞提示、超管警告 / 切断、人气榜和分区小时榜排名
    def __like_click(self, client, command):
        d = command.get('data') or {}
        base = ((d.get('uinfo') or {}).get('base') or {})
        medal = d.get('fans_medal') or {}
        self.hub.enter(int(d.get('uid') or 0), str(d.get('uname') or base.get('name') or ''), base.get('face') or '', 'like',
                       int(medal.get('guard_level') or 0) if medal.get('anchor_roomid') in (self.hub.state.room.get('room_real'), self.hub.state.room_id) else 0)
    _CMD_CALLBACK_DICT['LIKE_INFO_V3_CLICK'] = __like_click  # noqa

    def __warning(self, client, command):
        self.hub.room_warn('WARNING', command.get('msg') or (command.get('data') or {}).get('msg') or '')
    _CMD_CALLBACK_DICT['WARNING'] = __warning  # noqa

    def __cut_off(self, client, command):
        self.hub.room_warn('CUT_OFF', command.get('msg') or (command.get('data') or {}).get('msg') or '')
    _CMD_CALLBACK_DICT['CUT_OFF'] = __cut_off  # noqa

    def __pop_rank(self, client, command):
        d = command.get('data') or {}
        self.hub.room_update(pop_rank=int(d.get('rank') or 0))
    _CMD_CALLBACK_DICT['POPULAR_RANK_CHANGED'] = __pop_rank  # noqa

    def __area_rank(self, client, command):
        d = command.get('data') or {}
        self.hub.room_update(area_rank=int(d.get('rank') or 0), area_rank_name=str(d.get('rank_name') or ''))
    _CMD_CALLBACK_DICT['AREA_RANK_CHANGED'] = __area_rank  # noqa

    def __entry_effect(self, client, command):
        d = command.get('data', {})
        base = (d.get('uinfo') or {}).get('base') or {}
        name = base.get('name', '')
        if not name:
            cw = d.get('copy_writing', '')
            name = cw.split('<%', 1)[-1].split('%>', 1)[0] if '<%' in cw else ''
        self.hub.enter(d.get('uid', 0), name, base.get('face') or d.get('face', ''), 'enter',
                       d.get('privilege_type', 0))
    _CMD_CALLBACK_DICT['ENTRY_EFFECT'] = __entry_effect  # noqa

    def _on_danmaku(self, client, m: web_models.DanmakuMessage):
        emo = ''
        if m.dm_type == 1 and isinstance(m.emoticon_options, dict):
            emo = m.emoticon_options.get('url', '')
        # 弹幕里夹的小表情（[妙]、[哇] 这种）：B 站在附加信息里给了每个表情的图片地址
        try:
            emots = {k: v.get('url', '') for k, v in (m.extra_dict.get('emots') or {}).items() if isinstance(v, dict) and v.get('url')}
        except Exception:
            emots = {}
        try:
            reply = str(m.extra_dict.get('reply_uname') or '') if m.extra_dict.get('show_reply', True) else ''
        except Exception:
            reply = ''
        try:
            dmid = str(m.extra_dict.get('id_str') or '')
        except Exception:
            dmid = ''
        self.hub.danmaku(m.uid, m.uname, m.face, m.msg, m.medal_name, m.medal_level,
                         m.privilege_type, bool(m.admin), emo, m.medal_room_id, emots, getattr(m, 'medal_lit', 1),
                         getattr(m, 'wealth_level', 0) or 0, reply, dmid)

    def _on_gift(self, client, m: web_models.GiftMessage):
        if m.coin_type != 'gold':
            return  # 免费的银瓜子礼物不算收益
        if m.tid:
            if m.tid in self.seen:
                return
            self.seen.append(m.tid)
        # 盲盒按爆出来的礼物算流水，普通礼物按实付
        yuan = m.price * m.num / 1000 if m.blind_gift_name else m.total_coin / 1000
        self.hub.gift(m.uid, m.uname, m.face, m.gift_name, m.num, yuan,
                      m.gift_img_basic, m.guard_level, m.blind_gift_name, m.gift_id)

    def _on_user_toast_v2(self, client, m: web_models.UserToastV2Message):
        if m.source == 2:
            return  # 这种是重复通知
        # B 站的提示原文：「<%某某%> 在主播xx的直播间续费了舰长，今天是TA陪伴主播的第123天」—— 从里面拿开通/续费和第几天
        msg = str(m.toast_msg or '')
        op = '续费' if '续费' in msg else '开通' if '开通' in msg else ''
        d = re.search(r'第\s*(\d+)\s*天', msg)
        self.hub.guard_buy(m.uid, m.username, m.guard_level, m.num, m.price * m.num / 1000, m.unit or '月',
                           op=op, days=int(d.group(1)) if d else 0)

    def _on_super_chat(self, client, m: web_models.SuperChatMessage):
        self.hub.super_chat(m.id, m.uid, m.uname, m.face, m.price, m.message, m.guard_level, m.end_time, icon=m.background_icon or '')

    def _on_interact_word_v2(self, client, m: web_models.InteractWordV2Message):
        kind = {1: 'enter', 2: 'follow', 3: 'share', 5: 'follow'}.get(m.msg_type)
        if kind:
            self.hub.enter(m.uid, m.username, m.face, kind)


async def poll_room(hub, session, room_id):
    """每分钟问一次直播间信息和高能榜（高能用户数 ≈ 在线里比较活跃的人），顺便判断开播/下播/换场。"""
    ruid = 0
    while True:
        hub.wake.clear()
        try:
            async with session.get(f'https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}',
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                payload = await r.json(content_type=None)
                d = payload.get('data') if isinstance(payload, dict) else None
                if not isinstance(d, dict) or payload.get('code', 0) != 0 or type(d.get('live_status')) is not int or d.get('live_status') not in (0, 1, 2):
                    raise ValueError('房间信息无效，保留当前直播状态')
            ruid = d.get('uid', ruid)
            if ruid and getattr(hub, 'anchor_uid', 0) != ruid:
                # 主播名字（2026-11-26）：顶栏「切换直播间」上显示的，以前要在 config.json 写，没写就一直叫「主播」
                # 主播头像（2026-11-28）：没登录（游客）时 B 站把弹幕的账号编号藏了，只能按头像认出主播本人
                try:
                    async with session.get(f'https://api.live.bilibili.com/live_user/v1/Master/info?uid={ruid}',
                                           timeout=aiohttp.ClientTimeout(total=10)) as r2:
                        info = ((await r2.json(content_type=None)).get('data') or {}).get('info') or {}
                    uname = str(info.get('uname') or '').strip()[:40]
                    face = str(info.get('face') or '').strip()
                    if uname or face:
                        hub.anchor_uid = ruid
                        hub.room_update(**({'anchor_name': uname} if uname and not getattr(hub, 'anchor_fixed', True) else {}),
                                        **({'anchor_face': face} if face.startswith('http') else {}))
                except Exception as e:
                    log.info('查主播名字失败：%s', e)
            live = 1 if d.get('live_status') == 1 else 0
            start = live_ts(d.get('live_time', ''))
            s, prev = hub.state, hub.state.room.get('live')
            merged = bool(live and start and start in (s.live_merged or []))
            if live and start and not merged and s.live_start and s.live_start != start and hub.can_resume(start):
                # 断流 5 分钟内又开播：不清零，接着算同一场（2026-11-23）
                hub.resume_session(start)
                merged = True
            if live and start and not merged and (s.summarized or s.archive_pending or
                    (s.live_start and s.live_start != start) or s.session_start < start - 60):
                # 本场数据是这场开播之前就有的（上一场的，或者程序关着的时候换了一场）：先存历史再清零
                log.info('新的一场（%s 开播），本场数据清零', d.get('live_time'))
                hub.new_session('自动结算')
            if live and start and not merged:
                s.live_start = start
            if live:
                hub.live_seen_at = time.time()
            hub.room_update(title=d.get('title', ''), live=live, area=d.get('area_name', ''), area_id=d.get('area_id', 0),
                            live_time=d.get('live_time', ''), cover=d.get('user_cover', ''), uid=ruid,
                            room_real=d.get('room_id', room_id))
            if not live and prev == 1:
                hub.close_broadcast('下播')
            elif not live and prev is None and s.was_live and not s.summarized:
                hub.close_broadcast('自动结算', s.last_activity or None)
            if ruid:
                # 在线榜：这个接口连没有分数的在线观众也给（高能榜接口只给有分数的），分数高的在前
                top, seen, online = [], set(), hub.state.room.get('online', 0)
                for page in range(1, 6):
                    url = ('https://api.live.bilibili.com/xlive/general-interface/v1/rank/queryContributionRank'
                           f"?ruid={ruid}&room_id={d.get('room_id', room_id)}&page={page}&page_size=100&type=online_rank&switch=contribution_rank")
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                        g = (await r.json(content_type=None)).get('data') or {}
                    fresh = [x for x in (g.get('item') or []) if x.get('uid') not in seen]
                    for x in fresh:
                        seen.add(x.get('uid'))
                        top.append({'uid': x.get('uid'), 'name': x.get('name'), 'face': x.get('face'),
                                    'score': x.get('score') or 0, 'guard': x.get('guard_level', 0)})
                    online = max(g.get('count') or 0, len(top)) if page == 1 else online
                    if not fresh or len(top) >= (g.get('count') or 0):
                        break
                hub.room_update(online=online, top=top)
        except Exception as e:
            log.warning('查直播间信息失败：%s', e)
        try:
            await asyncio.wait_for(hub.wake.wait(), 60)
            await asyncio.sleep(3)  # 刚开播时 B 站接口要过一会儿才有开播时间
        except asyncio.TimeoutError:
            pass


# 从 main 搬出，依赖显式传入，离线测试不需要启动真实连接。
async def backfill_side_room(session, h, room):
    """切过去时先放上那边最近的弹幕（2026-11-21）：B 站历史弹幕接口给最近 10 条；没给就算了。"""
    try:
        async with session.get('https://api.live.bilibili.com/xlive/web-room/v1/dM/gethistory', params={'roomid': str(room), 'room_type': '0'},
                               headers={'Referer': f'https://live.bilibili.com/{room}'}, timeout=aiohttp.ClientTimeout(total=8)) as r:
            j = await r.json(content_type=None)
        rows = ((j.get('data') or {}).get('room') or []) if isinstance(j, dict) else []
    except Exception as ex:
        log.warning('拿别的直播间最近弹幕失败：%s', ex)
        return
    for x in rows[-10:]:
        if not isinstance(x, dict):
            continue
        user = x.get('user') if isinstance(x.get('user'), dict) else {}
        base = user.get('base') if isinstance(user.get('base'), dict) else {}
        md = x.get('medal') if isinstance(x.get('medal'), list) else []
        um = user.get('medal') if isinstance(user.get('medal'), dict) else {}
        emo = ((x.get('emoticon') or {}).get('url') or '') if x.get('dm_type') == 1 and isinstance(x.get('emoticon'), dict) else ''
        n = len(h.state.dm)
        try:  # 2026-11-21 补漏洞：数字字段不是数字（B 站给了怪数据）就跳过这一条，别的照常补
            uid, lv = int(x.get('uid') or user.get('uid') or 0), int((md[0] if md else 0) or um.get('level') or 0)
            guard, mroom = int(x.get('guard_level') or 0), int((md[3] if len(md) > 3 else 0) or 0)
        except (TypeError, ValueError):
            continue
        h.danmaku(uid, str(x.get('nickname') or base.get('name') or ''), str(base.get('face') or ''),
                  str(x.get('text') or ''), str((md[1] if len(md) > 1 else '') or um.get('name') or ''), lv,
                  guard, bool(x.get('isadmin')), emo, mroom, None, 1, 0, '', str(x.get('id_str') or ''))
        if len(h.state.dm) > n:
            t = live_ts(str(x.get('timeline') or ''))
            if t:
                h.state.dm[-1]['t'] = int(t)
