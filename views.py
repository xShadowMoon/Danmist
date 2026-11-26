"""不同的人能看到什么（2026-11-26 从 server.py 搬出来，只搬家没改逻辑）：
普通链接（viewer_*）、公开推送（public_view）、OBS 不显示价格时（obs_view）。都是纯函数。"""




def public_view(data):
    """公开单次礼物/SC金额用于上屏；隐藏收入汇总、个人消费和管理资料。递归处理嵌套事件。"""
    private = {'flow', 'income', 'total', 'spend', 'brief', 'rank', 'gift_stats', 'viewers',
               'notes', 'songbook', 'library', 'responses', 'backing', 'req_ids', 'note', 'profiles', 'profile', 'sc_read', 'mutes', 'title_presets'}
    if isinstance(data, dict):
        return {k: public_view(v) for k, v in data.items() if k not in private}
    if isinstance(data, list):
        return [public_view(v) for v in data]
    return data


# ---- 普通链接（不是管理身份，也不是 OBS 页面）----
# 2026-11-14 用户要求大量减少；2026-11-21 用户又说「大部分功能可以公开，但不能看到主播的各种数据和历史」：
# 给：实时弹幕、SC（带金额）、礼物（不带价格）、上舰（不带价格）、进房和关注、观众名单（不带花了多少）、舰长名单、
#     点歌、歌单、在线 / 看过 / 点赞 / 弹幕数 / 直播时长这些 B 站上本来就看得到的数字。
# 不给：收益流水、礼物价格、谁送了多少、礼物榜、历史场次、下播期间、备注、曲库、整场弹幕往上翻。
# 这里是按「只挑要给的」来写的：以后本场数据里加了新东西，默认不会漏给普通链接。
VIEWER_ROOM = ('title', 'live', 'room_real', 'bili_ok', 'online', 'watched', 'watched_text', 'live_time', 'likes', 'area', 'area_id',
               'area_rank', 'area_rank_name', 'pop_rank', 'top', 'uid', 'face', 'cover', 'guard', 'up_at', 'down_at')


VIEWER_ENTER = ('t', 'uid', 'name', 'face', 'kind', 'guard', 'plat')


VIEWER_GUARD = ('id', 't', 'uid', 'name', 'face', 'level', 'level_name', 'num', 'unit', 'op', 'days', 'fx', 'fxj')


VIEWER_USER = ('uid', 'name', 'face', 'first', 'last', 'dm', 'enter', 'guard', 'medal')


VIEWER_REQ = ('id', 't', 'uid', 'name', 'face', 'guard', 'kind', 'text', 'song', 'done', 'over', 'queued_id')


VIEWER_GUARDLIST = ('uid', 'name', 'face', 'level', 'days', 't')


VIEWER_DM = ('t', 'uid', 'name', 'face', 'text', 'medal', 'medal_level', 'medal_room', 'medal_dim', 'wealth', 'reply', 'guard', 'admin', 'emoticon', 'emots', 'i', 'kind', 'link', 'plat')


VIEWER_SC = ('id', 't', 'uid', 'name', 'face', 'price', 'text', 'guard', 'end', 'icon')


VIEWER_GIFT = ('id', 't', 'uid', 'name', 'face', 'gift', 'num', 'img', 'guard', 'blind', 'source', 'plat')


VIEWER_SONG = ('id', 'name', 'done', 'now', 'done_at', 'artist', 'tags')


def pick(row, keys):
    return {k: row[k] for k in keys if k in row}


def viewer_gift(g):
    out = pick(g, VIEWER_GIFT)
    out['big'] = (g.get('yuan') or 0) >= 50  # 只说是不是大礼物（网页上加个底色），不给价格
    return out


def viewer_snapshot(snap):
    def rows(k, keys):
        return [pick(x, keys) for x in snap.get(k) or [] if isinstance(x, dict)]
    return {'room_id': snap.get('room_id'), 'room': pick(snap.get('room') or {}, VIEWER_ROOM), 'session_start': snap.get('session_start') or 0, 'live_from': snap.get('live_from') or 0,
            'flow': {'gift': 0, 'sc': 0, 'guard': 0}, 'dm': rows('dm', VIEWER_DM),
            'gifts': [viewer_gift(g) for g in snap.get('gifts') or []], 'scs': rows('scs', VIEWER_SC),
            'songs': rows('songs', VIEWER_SONG), 'enters': rows('enters', VIEWER_ENTER), 'guards': rows('guards', VIEWER_GUARD),
            # 送过东西的人排在后面，原样给就等于说了谁花过钱：只按最近来过排，最多 500 个
            'users': sorted(rows('users', VIEWER_USER), key=lambda u: -(u.get('last') or 0))[:500],
            'reqs': rows('reqs', VIEWER_REQ), 'user_count': snap.get('user_count') or 0, 'dm_total': snap.get('dm_total') or 0,
            'bot_uids': snap.get('bot_uids') or []}


def viewer_view(kind, data):
    """一条推送给普通链接时长什么样；返回 None 就是不发。"""
    if kind == 'dm':
        return pick(data, VIEWER_DM)
    if kind == 'sc':
        return {'item': pick(data['item'], VIEWER_SC)}
    if kind == 'gift':
        return {'item': viewer_gift(data['item'])}
    if kind == 'songs':
        return [pick(x, VIEWER_SONG) for x in data]
    if kind == 'room':
        return pick(data, VIEWER_ROOM)
    if kind in ('enter', 'enter_update'):
        return pick(data, VIEWER_ENTER)
    if kind == 'guard':
        if not isinstance(data.get('item'), dict):
            return None
        out = {'item': pick(data['item'], VIEWER_GUARD)}
        if isinstance(data.get('user'), dict):
            out['user'] = pick(data['user'], VIEWER_USER)
        return out
    if kind == 'guards_all':
        return [pick(x, VIEWER_GUARD) for x in data]
    if kind == 'face':
        return pick(data, ('uid', 'face'))
    if kind == 'music':
        return data
    if kind == 'guardlist':
        return [pick(x, VIEWER_GUARDLIST) for x in data]
    if kind == 'req':
        return pick(data, VIEWER_REQ)
    if kind == 'reqs':
        return [pick(x, VIEWER_REQ) for x in data]
    if kind == 'xrooms':
        return {'open': True, 'rooms': data.get('rooms') or []} if data.get('open') else {'open': False, 'rooms': []}
    if kind == 'snapshot':
        return viewer_snapshot(data)
    if kind in ('emots', 'ver'):
        return data
    return None


def obs_view(kind, data, gm=0.0):
    """OBS 网址没开「显示价格」时（2026-11-21 用户：普通链接也能生成 OBS 网址，别让人拿到每个礼物的价格）：
    礼物、上舰去掉价格，只说是不是大礼物（≥50 元）、够不够网址里设的最低价。data 已经是 public_view 过的。"""
    def gift(g):
        if not isinstance(g, dict):
            return g
        out = {k: v for k, v in g.items() if k != 'yuan'}
        y = g.get('yuan') or 0
        out['big'] = y >= 50
        out['gm_ok'] = y >= gm
        return out

    def guard(g):
        return {k: v for k, v in g.items() if k != 'yuan'} if isinstance(g, dict) else g
    if kind == 'gift' and isinstance(data, dict):
        return {**{k: v for k, v in data.items() if k != 'item'}, 'item': gift(data.get('item'))}
    if kind == 'guard' and isinstance(data, dict):
        return {**{k: v for k, v in data.items() if k != 'item'}, 'item': guard(data.get('item'))}
    if kind == 'guards_all' and isinstance(data, list):
        return [guard(g) for g in data]
    if kind == 'snapshot' and isinstance(data, dict):
        return {**data, 'gifts': [gift(g) for g in data.get('gifts') or []], 'guards': [guard(g) for g in data.get('guards') or []]}
    return data
