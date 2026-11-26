"""集中校验网页、HTTP 与直播事件输入；不把错误类型悄悄转成可保存的字符串。"""
import math
import re
import time
from urllib.parse import urlsplit

from profiles import validate_profile
from workbench import clean_song

SID = re.compile(r'\d{8}-\d{4}(?:-[0-9a-f]{12})?')
MAX_UID = 2**63 - 1
MAX_TIME = 4102444800


class InputError(ValueError):
    pass


def text(value, name, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise InputError(f'{name}格式不对，最多 {limit} 字')
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value) or '\x00' in value:
        raise InputError(f'{name}含无效字符')
    return value


def integer(value, name, low=0, high=MAX_UID):
    if type(value) is not int or not low <= value <= high:
        raise InputError(f'{name}需要 {low} 到 {high} 的整数')
    return value


def number(value, name, low=0, high=10**15):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise InputError(f'{name}数值不对')
    return value


def boolean(value, name):
    if type(value) is not bool:
        raise InputError(f'{name}需要 true 或 false')
    return value


def url(value, name='图片地址', limit=2048):
    text(value, name, limit)
    if value:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
                raise ValueError()
        except ValueError:
            raise InputError(f'{name}需要 http 或 https 地址') from None
    return value


def safe_url(value):
    """图片地址不对就当没有图：头像、表情这些只是装饰，不能因为它丢掉整条弹幕或礼物。"""
    try:
        return url(value)
    except InputError:
        return ''


def song(row):
    if not isinstance(row, dict):
        raise InputError('歌曲需要是一个对象')
    limits = {'name': 80, 'artist': 80, 'key': 24, 'backing': 1500, 'note': 1000, 'lyrics': 8000, 'level': 8}
    text(row.get('name'), '歌名', 80, True)
    for field, limit in limits.items():
        if field in row:
            text(row[field], field, limit)
    if 'backing' in row:
        url(row['backing'], '伴奏链接', 1500)
    if 'available' in row:
        boolean(row['available'], '是否可点')
    tags = row.get('tags', [])
    if isinstance(tags, str):
        text(tags, '标签', 300)
        tags = tags.replace('，', ',').split(',')
    if not isinstance(tags, list) or len(tags) > 12:
        raise InputError('标签最多 12 个')
    for tag in tags:
        text(tag, '标签', 24)
    return clean_song(row)



def sc_id(value):
    if type(value) is int:
        integer(value, 'SC 编号', 1)
        return str(value)
    return text(value, 'SC 编号', 80, True)


def mute_id(value):
    if type(value) is int:
        return str(integer(value, '禁言编号', 1))
    text(value, '禁言编号', 19, True)
    if not re.fullmatch(r'[1-9][0-9]{0,18}', value) or int(value) > MAX_UID:
        raise InputError('禁言编号格式不对')
    return value


def mute_row(row):
    if not isinstance(row, dict):
        raise InputError('禁言条目格式不对')
    out = {'id': mute_id(row.get('id')), 'uid': integer(row.get('tuid'), '观众 uid', 1),
           'name': text(row.get('tname'), '名字', 64, True), 'until': None, 'until_text': '期限未知', 'scope': 'unknown'}
    # 只返回需要的字段，其余已知上游字段也校验，避免把畸形条目误认成有效记录。
    for key in ('name', 'ctime', 'block_end_time', 'msg'):
        if key in row:
            text(row[key], key, {'name': 64, 'ctime': 32, 'block_end_time': 32, 'msg': 500}[key])
    if 'uid' in row:
        integer(row['uid'], '操作账号 uid', 1)
    if 'face' in row:
        url(row['face'])
    if 'is_anchor' in row:
        integer(row['is_anchor'], '主播标记', 0, 1)
    if 'admin_level' in row:
        integer(row['admin_level'], '权限级别', 0, 1)
    if 'is_mystery' in row:
        boolean(row['is_mystery'], '隐私标记')
    kind = row.get('type')
    if kind is not None:
        integer(kind, '禁言期限类型', 0, 2)
    end = row.get('block_end_time', '')
    if kind == 2:
        out.update(scope='session', until_text='到本场结束')
    elif kind == 0:
        out.update(scope='permanent', until_text='长期禁言')
    elif end:
        import datetime as dt
        try:
            stamp = dt.datetime.strptime(end, '%Y-%m-%d %H:%M:%S').replace(tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp()
            number(stamp, '禁言结束时间', 0, MAX_TIME)
        except ValueError:
            raise InputError('禁言结束时间格式不对') from None
        out.update(scope='timed', until=int(stamp), until_text=end + '（北京时间）')
    elif kind == 1:
        raise InputError('禁言结束时间缺失')
    return out


def clean_sc_read(value, scs):
    if not isinstance(value, list):
        return []
    current = {str(row['id']) for row in scs}
    kept, seen = [], set()
    for raw in value:
        try:
            sid = sc_id(raw)
        except ValueError:
            continue
        if sid in current and sid not in seen:
            kept.append(sid)
            seen.add(sid)
            if len(kept) == 5000:
                break
    return kept


COMMAND_FIELDS = {
    'mute_list': {'acct'}, 'unmute': {'id', 'acct'}, 'gift_thank': {'id', 'done'},
    'sc_read': {'id', 'read'}, 'sc_read_all': set(),
    'admin_link_list': set(), 'admin_link_create': {'name', 'days', 'host'},
    'admin_link_revoke': {'id'}, 'admin_link_rotate': {'name', 'days'}, 'admin_link_open_del': {'id', 't'},
    'reset': set(), 'obs_test': set(), 'areas': set(), 'acct_qr': set(),
    'profile_list': set(), 'profile_get': {'name'}, 'profile_save': {'name', 'content'}, 'profile_delete': {'name'},
    'song_add': {'id', 'text', 'req_id'}, 'song_done': {'id', 'text', 'req_id', 'done'},
    'song_del': {'id', 'text', 'req_id'}, 'song_clear': {'id', 'text', 'req_id'},
    'song_now': {'id', 'text', 'req_id'}, 'song_next': {'id', 'text', 'req_id', 'expected_now'},
    'song_move': {'id', 'text', 'req_id', 'before', 'direction'},
    'library_save': {'song'}, 'library_import': {'rows'}, 'library_delete': {'name'},
    'req_rules': {'max', 'medal'}, 'req_done': {'id', 'kind'}, 'req_del': {'id', 'kind'}, 'req_clear': {'id', 'kind'},
    'note_set': {'uid', 'name', 'text'}, 'say': {'text', 'acct', 'reply_uid', 'reply_dmid'}, 'mute': {'uid', 'name', 'acct'},
    'news_get': set(), 'news_set': {'acct', 'text'},
    'room_edit': {'acct', 'title', 'area_id'}, 'acct_poll': {'key'}, 'acct_info': {'acct'}, 'acct_logout': {'acct'},
    'tpre_set': {'list'}, 'xrooms_set': {'open', 'rooms'}, 'live_start': {'acct', 'area_id', 'title'}, 'live_stop': {'acct'},
    'lan_set': {'on'},
    'update_download': set(), 'update_restart': set(), 'open_mode': {'mode'}, 'make_shortcut': set(),
    'music_rules': {'on', 'mode', 'src', 'need_ok', 'skip', 'max', 'medal', 'guard', 'wealth', 'follow', 'maxdur'},
    'music_next': set(), 'music_ok': {'id'}, 'music_del': {'id'}, 'music_top': {'id'},
    'music_qr': {'src'}, 'music_poll': {'src', 'key'}, 'music_logout': {'src'}, 'music_cookie': {'src', 'cookie'},
    'plat_set': {'rooms'}, 'plat_show': {'plat', 'room', 'show'},
}

TITLE_PRESETS_MAX = 12
XROOMS_MAX = 10  # 普通链接能切的直播间最多几个（2026-11-21 用户：要有上限）


def xrooms(c):
    """普通链接能切到哪些直播间（2026-11-21）：{open 开没开, rooms [{room 房间号, name 名字}]}"""
    if not isinstance(c, dict) or set(c) - {'open', 'rooms'}:
        raise InputError('直播间名单格式不对')
    rows = c.get('rooms', [])
    if not isinstance(rows, list) or len(rows) > XROOMS_MAX:
        raise InputError(f'直播间最多 {XROOMS_MAX} 个')
    out, seen = [], set()
    for r in rows:
        if not isinstance(r, dict) or set(r) - {'room', 'name'}:
            raise InputError('直播间名单格式不对')
        room = integer(r.get('room'), '房间号', 1, 10**12 - 1)
        text(r.get('name', ''), '直播间名字', 40)
        if room not in seen:
            seen.add(room)
            out.append({'room': room, 'name': str(r.get('name', '')).strip()})
    return {'open': boolean(c.get('open', False), '开关'), 'rooms': out}


def title_preset(row):
    """常用标题（2026-11-18）：{name 名字, title 标题, area_id 分区编号, area 分区名}"""
    if not isinstance(row, dict) or set(row) - {'name', 'title', 'area_id', 'area'}:
        raise InputError('常用标题格式不对')
    text(row.get('name', ''), '常用标题的名字', 12)
    text(row.get('title', ''), '标题', 40)
    integer(row.get('area_id', 0), '分区', 0, 10**7)
    text(row.get('area', ''), '分区名', 30)
    if not str(row.get('title', '')).strip() and not row.get('area_id'):
        raise InputError('常用标题至少要有标题或分区')
    return {'name': str(row.get('name', '')).strip(), 'title': str(row.get('title', '')).strip(),
            'area_id': int(row.get('area_id', 0)), 'area': str(row.get('area', ''))}


def title_presets(rows):
    if not isinstance(rows, list) or len(rows) > TITLE_PRESETS_MAX:
        raise InputError(f'常用标题最多 {TITLE_PRESETS_MAX} 个')
    return [title_preset(r) for r in rows]


def validate_command(c, clean_rules):
    cmd = c.get('cmd')
    if not isinstance(cmd, str) or cmd not in COMMAND_FIELDS:
        raise InputError('不支持这个操作')
    if set(c) - COMMAND_FIELDS[cmd] - {'cmd', 'rid'}:
        raise InputError('操作里有不支持的字段')
    if 'rid' in c:
        text(c['rid'], '请求编号', 80, True)
    if cmd.startswith('admin_link_'):
        if cmd in ('admin_link_revoke', 'admin_link_open_del'):
            text(c.get('id'), '链接编号', 32, True)
            if cmd == 'admin_link_open_del':
                integer(c.get('t'), '打开时间', 1, 4102444800)
            if not re.fullmatch(r'[0-9a-f]{32}', c['id']):
                raise InputError('链接编号格式不对')
        if cmd in ('admin_link_create', 'admin_link_rotate'):
            text(c.get('name', ''), '链接名字', 12)
            days = c.get('days', 30)
            if type(days) is not int or days not in (0, 1, 7, 30):
                raise InputError('有效期请选择 1、7、30 天或长期')
            if 'host' in c and type(c['host']) is not bool:
                raise InputError('主播专属只能是开或关')
    if cmd == 'unmute':
        mute_id(c.get('id'))
    elif cmd == 'sc_read':
        sc_id(c.get('id'))
        boolean(c.get('read'), '已读状态')
    elif cmd == 'gift_thank':
        text(c.get('id'), '礼物编号', 64, True)
        boolean(c.get('done'), '已感谢')
    elif cmd == 'tpre_set':
        title_presets(c.get('list'))
    elif cmd == 'plat_show':
        if c.get('plat') != 'douyin' or not re.fullmatch(r'\d{1,20}', str(c.get('room') or '')):
            raise InputError('只有抖音的直播间能显示窗口')
        boolean(c.get('show'), '显示窗口')
    elif cmd == 'open_mode':
        if c.get('mode') not in ('app', 'web'):
            raise InputError('打开方式只能是软件窗口或浏览器')
    elif cmd == 'lan_set':
        boolean(c.get('on'), '手机打开')
    elif cmd in ('music_ok', 'music_del', 'music_top'):
        text(c.get('id'), '点歌编号', 32, True)
    elif cmd in ('music_qr', 'music_poll', 'music_logout', 'music_cookie'):
        if c.get('src') not in ('163', 'qq'):
            raise InputError('不支持这个音乐平台')
        if cmd == 'music_cookie':
            text(c.get('cookie'), '登录信息', 8000, True)
        if cmd == 'music_poll':
            text(c.get('key'), '二维码编号', 64, True)
    elif cmd == 'xrooms_set':
        xrooms({'open': c.get('open', False), 'rooms': c.get('rooms', [])})
    elif cmd in ('live_start', 'live_stop'):
        text(c.get('acct'), '账号标识', 128, True)
        if cmd == 'live_start':
            integer(c.get('area_id', 0), '分区', 0, 10**7)
            text(c.get('title', ''), '标题', 40)
    if 'acct' in c:
        text(c['acct'], '账号标识', 128)
        if c['acct'] and not re.fullmatch(r'[A-Za-z0-9_-]{20,128}', c['acct']):
            raise InputError('账号标识格式不对')
    if cmd.startswith('profile_') and cmd != 'profile_list':
        text(c.get('name'), '方案名字', 12, True)
        if cmd == 'profile_save':
            validate_profile(c['name'], c.get('content'), int(time.time()))
    elif cmd.startswith('song_'):
        for field in ('id', 'req_id', 'before'):
            if field in c:
                text(c[field], field, 80)
        if 'text' in c:
            text(c['text'], '歌单内容', 5000)
        if cmd == 'song_add':
            text(c.get('text'), '歌单内容', 5000, True)
            lines = [line.strip() for line in c['text'].splitlines() if line.strip()]
            if not 1 <= len(lines) <= 50 or any(len(line) > 80 for line in lines):
                raise InputError('一次最多 50 首，每个歌名最多 80 字')
        if cmd in ('song_done', 'song_del', 'song_now', 'song_move'):
            text(c.get('id'), '歌曲编号', 80, True)
        if cmd == 'song_done' and 'done' in c:
            boolean(c['done'], '完成状态')
        if cmd == 'song_move':
            if 'before' not in c and 'direction' not in c:
                raise InputError('请指定移动位置')
            if 'direction' in c and (type(c['direction']) is not int or c['direction'] not in (-1, 1)):
                raise InputError('移动方向只能是 -1 或 1')
        if cmd == 'song_clear' and c.get('id', '') not in ('', 'all', 'done'):
            raise InputError('清理范围不对')
        if 'expected_now' in c and c['expected_now'] is not None:
            text(c['expected_now'], '当前歌曲编号', 80, True)
    elif cmd in ('library_save', 'library_import'):
        rows = c.get('rows') if cmd == 'library_import' else [c.get('song')]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 3000:
            raise InputError('一次请导入 1–3000 首歌')
        for row in rows:
            song(row)
    elif cmd == 'library_delete':
        text(c.get('name'), '歌名', 80, True)
    elif cmd == 'req_rules':
        if not any(k in c for k in ('max', 'medal')):
            raise InputError('请填写点歌规则')
        for field, high in (('max', 50), ('medal', 40)):
            if field in c:
                integer(c[field], field, 0, high)
        clean_rules(c)
    elif cmd in ('req_done', 'req_del', 'req_clear'):
        if cmd != 'req_clear':
            text(c.get('id'), '请求编号', 80, True)
        elif 'id' in c:
            text(c['id'], '请求编号', 80)
        if 'kind' in c and c['kind'] not in ('song', 'ask'):
            raise InputError('请求类型不对')
        if cmd == 'req_clear' and 'kind' not in c:
            raise InputError('请指定请求类型')
    elif cmd in ('note_set', 'mute'):
        integer(c.get('uid'), '观众 uid', 1)
        text(c.get('name', ''), '名字', 64)
        if cmd == 'note_set':
            text(c.get('text'), '备注', 60)
    elif cmd == 'say':
        text(c.get('text'), '弹幕', 40, True)
        # 回复某条弹幕（2026-11-21）：被回复的人的 uid 和那条弹幕的编号
        if 'reply_uid' in c:
            integer(c['reply_uid'], '回复的人', 0, MAX_UID)
        if 'reply_dmid' in c:
            text(c['reply_dmid'], '回复的弹幕', 64)
            if c['reply_dmid'] and not re.fullmatch(r'[0-9a-zA-Z]+', c['reply_dmid']):
                raise InputError('回复的弹幕编号不对')
    elif cmd == 'news_set':
        text(c.get('acct'), '账号标识', 128, True)
        text(c.get('text'), '公告', 60)
    elif cmd == 'room_edit':
        text(c.get('acct'), '账号标识', 128, True)
        if 'title' in c:
            text(c['title'], '标题', 40)
        if 'area_id' in c:
            integer(c['area_id'], '分区', 0, 10**7)
        if not c.get('title', '').strip() and not c.get('area_id'):
            raise InputError('请填写标题或分区')
    elif cmd == 'acct_poll':
        text(c.get('key'), '二维码标识', 128, True)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', c['key']):
            raise InputError('二维码标识格式不对')
    elif cmd in ('acct_info', 'acct_logout'):
        text(c.get('acct'), '账号标识', 128, True)
    return c


def query_integer(value, name, low, high, default=None):
    if value is None or value == '':
        if default is not None:
            return default
        raise InputError(f'缺少{name}')
    if not isinstance(value, str) or len(value) > 20 or not value.isascii() or not value.isdecimal():
        raise InputError(f'{name}需要是整数')
    return integer(int(value), name, low, high)


def validate_http(kind, query, match):
    for key in query:
        text(key, '参数名', 64)
        text(query[key], '参数', 4096)
        if hasattr(query, 'getall') and len(query.getall(key)) > 1:
            raise InputError('参数不能重复')
    if kind in ('hist_get', 'hist_dm', 'hist_delete'):
        sid = match.get('sid')
        if not isinstance(sid, str) or not SID.fullmatch(sid):
            raise InputError('场次编号格式不对')
    if kind == 'mascot_put':  # 看板娘图标（2026-11-26）
        size = query_integer(query.get('size'), '图标尺寸', 32, 512)
        if size not in (32, 64, 192, 256, 512):
            raise InputError('图标尺寸不对')
        return {'size': size}
    if kind == 'viewer_info':
        return {'uid': query_integer(match.get('uid'), '观众 uid', 1, MAX_UID)}
    if kind in ('dm_older', 'hist_dm'):
        q = query.get('q', '')
        text(q, '搜索内容', 500)
        return {'before': query_integer(query.get('before'), '翻页位置', 0, 10**12) if query.get('before') else None,
                'limit': query_integer(query.get('limit'), '每页条数', 1, 500, 200), 'q': q,
                'uid': query_integer(query.get('uid'), '观众 uid', 0, MAX_UID, 0)}
    if kind == 'img_proxy':
        value = query.get('u', '')
        url(value)
        parsed = urlsplit(value)
        other = parsed.scheme == 'https' and (parsed.hostname or '').endswith(('.douyucdn.cn', '.msstatic.com', '.huya.com', '.douyinpic.com'))  # 斗鱼、虎牙的头像和礼物图（2026-11-25）
        if (parsed.hostname not in ('i0.hdslb.com', 'i1.hdslb.com', 'i2.hdslb.com', 's1.hdslb.com') and not other) or parsed.netloc != parsed.hostname:
            raise InputError('不支持这个图片地址')
        return {'u': value}
    return {}


def event(kind, values):
    integer(values.get('uid'), 'uid', 0)
    text(values.get('name'), '名字', 64)
    if 'face' in values:
        url(values['face'])
    if 'guard' in values:
        integer(values['guard'], '舰长等级', 0, 3)
    if kind == 'dm':
        text(values.get('text'), '弹幕', 500)
        text(values.get('medal', ''), '粉丝牌', 64)
        integer(values.get('medal_level', 0), '粉丝牌等级', 0, 1000)
        integer(values.get('medal_room', 0), '粉丝牌房间', 0)
        boolean(values.get('admin', False), '房管状态')
        url(values.get('emoticon', ''))
        emots = values.get('emots')
        if emots is not None and (not isinstance(emots, dict) or len(emots) > 4096):
            raise InputError('表情格式不对')
    elif kind == 'enter':
        if values.get('kind') not in ('enter', 'follow', 'share', 'like'):
            raise InputError('进房类型不对')
    elif kind == 'gift':
        text(values.get('gift_name'), '礼物名', 80, True)
        text(values.get('blind', ''), '盲盒名', 80)
        integer(values.get('num'), '礼物数量', 1, 10**6)
        number(values.get('yuan'), '礼物金额', 0, 10**9)
        url(values.get('img', ''))
    elif kind == 'sc':
        sid = values.get('sc_id')
        if type(sid) is int:
            integer(sid, 'SC 编号', 1)
        else:
            text(sid, 'SC 编号', 80, True)
        number(values.get('price'), 'SC 金额', 0, 10**9)
        text(values.get('text'), 'SC 内容', 500)
        number(values.get('end', 0), 'SC 结束时间', 0, MAX_TIME)
    elif kind == 'guard':
        integer(values.get('level'), '舰长等级', 1, 3)
        integer(values.get('num'), '上舰数量', 1, 10000)
        number(values.get('yuan'), '上舰金额', 0, 10**9)
        text(values.get('unit'), '上舰单位', 8, True)  # 审查时放宽：单位没见过也不能把一笔上舰丢掉
    return values


# 读盘沿用相同字段校验，只跳过坏条目，不因为一条损坏记录丢掉整个文件。
def clean_rows(rows, cleaner, limit=None):
    import logging
    if not isinstance(rows, list):
        if rows not in (None, []):
            logging.getLogger('xiaowu').warning('跳过格式不对的数据列表')
        return []
    kept, bad = [], 0
    for row in rows:
        try:
            kept.append(cleaner(row))
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            bad += 1
    if bad:
        logging.getLogger('xiaowu').warning('读取数据时跳过 %d 条坏记录', bad)
    return kept[-limit:] if limit else kept


def event_row(kind, row):
    if not isinstance(row, dict):
        raise InputError('记录不是对象')
    defaults = {'face': '', 'guard': 0}
    if kind == 'dm':
        defaults.update(medal='', medal_level=0, medal_room=0, admin=False, emoticon='')
    if kind == 'gift':
        defaults.update(img='', blind='')
    if kind == 'guard':
        defaults.update(unit='月')
    aliases = {'gift_name': 'gift', 'sc_id': 'id', 'price': 'price', 'text': 'text'}
    fields = {'t', 'uid', 'name', 'face', 'guard', 'id', 'i', 'thanked', 'medal', 'medal_level', 'medal_room', 'admin', 'emoticon', 'emots',
              'gift', 'num', 'yuan', 'img', 'blind', 'price', 'text', 'end', 'level', 'level_name', 'unit', 'kind', 'recovered', 'source', 'op', 'days', 'days_est', 'dmid', 'plat'}
    result = {**defaults, **{k: v for k, v in row.items() if k in fields}}
    values = {**result, **{key: result.get(value) for key, value in aliases.items() if value in result}}
    event(kind, values)
    number(result.get('t'), '记录时间', 0, MAX_TIME)
    if 'i' in result:
        integer(result['i'], '弹幕序号', 0, 10**12)
    if kind == 'guard' and 'op' in result and result['op'] not in ('开通', '续费'):
        raise InputError('上舰类型不对')
    if kind == 'guard' and 'days' in result:
        integer(result['days'], '陪伴天数', 1, 99999)
    if 'id' in result and kind != 'sc':
        text(result['id'], '记录编号', 80, True)
    if 'plat' in result and result['plat'] not in ('douyu', 'huya', 'douyin'):
        result.pop('plat')
    if 'recovered' in result:
        boolean(result['recovered'], '补录状态')
    # 2026-11-21 补漏洞：存档里的弹幕编号、「陪伴天数是推出来的」标记坏了就只丢这个字段，这一条记录照样留着
    if 'dmid' in result and not (isinstance(result['dmid'], str) and re.fullmatch(r'[0-9a-zA-Z]{1,64}', result['dmid'])):
        result.pop('dmid')
    if 'days_est' in result and not isinstance(result['days_est'], bool):
        result.pop('days_est')
    for key in ('level_name', 'source'):
        if key in result:
            text(result[key], key, 64)
    if 'emots' in result:
        import retention
        result['emots'] = retention.trim_emots(result['emots']) if isinstance(result['emots'], dict) else {}
    return result


def queue_row(row):
    if not isinstance(row, dict):
        raise InputError('歌单记录不是对象')
    text(row.get('id'), '歌曲编号', 80, True)
    text(row.get('name'), '歌名', 80, True)
    boolean(row.get('done'), '已唱状态')
    out = {k: row[k] for k in ('id', 'name', 'done')}
    for key in ('now',):
        if key in row:
            out[key] = boolean(row[key], key)
    if 'done_at' in row:
        out['done_at'] = number(row['done_at'], '完成时间', 0, MAX_TIME)
    ids = row.get('req_ids', [])
    if not isinstance(ids, list) or len(ids) > 300:
        raise InputError('关联请求不对')
    out['req_ids'] = [text(i, '关联编号', 80, True) for i in ids]
    return out


def fan_row(row):
    if not isinstance(row, dict):
        raise InputError('观众记录不是对象')
    out = {'uid': integer(row.get('uid'), 'uid', 1), 'name': text(row.get('name', ''), '名字', 64)}
    if 't' in row:
        out['t'] = number(row['t'], '时间', 0, MAX_TIME)
    return out


def request_row(row):
    if not isinstance(row, dict):
        raise InputError('请求记录不是对象')
    out = fan_row(row)
    out.update(id=text(row.get('id'), '请求编号', 80, True), t=number(row.get('t'), '时间', 0, MAX_TIME),
               text=text(row.get('text'), '请求内容', 500), song=text(row.get('song', ''), '歌名', 80),
               done=boolean(row.get('done'), '处理状态'), face=url(row.get('face', '')),
               guard=integer(row.get('guard', 0), '舰长等级', 0, 3))
    if row.get('kind') not in ('song', 'ask'):
        raise InputError('请求类型不对')
    out['kind'] = row['kind']
    for field in ('over', 'queued_id'):
        if field in row:
            out[field] = text(row[field], field, 80)
    if 'fans' in row:
        out['fans'] = clean_rows(row['fans'], fan_row, 10000)
    return out


def user_row(row):
    out = fan_row(row)
    out['face'] = url(row.get('face', ''))
    for key in ('first', 'last'):
        out[key] = number(row.get(key, 0), key, 0, MAX_TIME)
    for key in ('dm', 'enter', 'spend'):
        out[key] = number(row.get(key, 0), key)
    out['guard'] = integer(row.get('guard', 0), '舰长等级', 0, 3)
    out['medal'] = text(row.get('medal', ''), '粉丝牌', 80)
    return out


def outage_row(row):
    if not isinstance(row, dict):
        raise InputError('断线记录不是对象')
    down = number(row.get('down_at'), '断线时间', 0, MAX_TIME)
    up = row.get('up_at')
    if up is not None:
        number(up, '恢复时间', down, MAX_TIME)
    out = {'down_at': down, 'up_at': up}
    if 'recovery' in row:
        out['recovery'] = text(row['recovery'], '恢复记录', 100)
    if 'sc_added' in row:
        out['sc_added'] = integer(row['sc_added'], '补录数量', 0, 5000)
    return out


def mapping(value, cleaner, limit=None):
    if not isinstance(value, dict):
        return {}
    rows = clean_rows(list(value.items()), lambda pair: (text(pair[0], '索引', 160, True), cleaner(pair[0], pair[1])))
    return dict(rows[-limit:] if limit else rows)


def numeric_mapping(value, defaults=None):
    out = dict(defaults or {})
    if isinstance(value, dict):
        for key, val in value.items():
            try:
                text(key, '字段名', 80)
                out[key] = number(val, key)
            except ValueError:
                continue
    return out


def history_row(row):
    if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not SID.fullmatch(row['id']):
        raise InputError('历史编号无效')
    out = {'id': row['id']}
    for key in ('start', 'end', 'broadcast_start'):
        if key in row:
            out[key] = number(row[key], key, 0, MAX_TIME)
    for key in ('title', 'area', 'reason'):
        if key in row:
            out[key] = text(row[key], key, 256)
    for key in ('total', 'income', 'dm_total', 'user_count', 'sc_count', 'guard_count', 'peak_online', 'room_id', 'dm_log_count'):
        if key in row:
            out[key] = number(row[key], key)
    for key in ('flow', 'stats'):
        if key in row:
            out[key] = numeric_mapping(row[key])
    for key, kind in (('scs', 'sc'), ('guards', 'guard'), ('big_gifts', 'gift')):
        if key in row:
            out[key] = clean_rows(row[key], lambda r: event_row(kind, r))
    if 'rank' in row:
        out['rank'] = clean_rows(row['rank'], user_row, 100)
    if 'outages' in row:
        out['outages'] = clean_rows(row['outages'], outage_row, 200)
    if 'gift_stats' in row:
        out['gift_stats'] = clean_rows(row['gift_stats'], lambda r: {'name': text(r['name'], '礼物名', 165),
                                                                 'num': number(r['num'], '数量'), 'yuan': number(r['yuan'], '金额')})
    if 'viewers' in row:
        def viewer(r):
            if not isinstance(r, list) or len(r) != 5:
                raise InputError('观众历史格式不对')
            return [integer(r[0], 'uid', 1), text(r[1], '名字', 64), number(r[2], '弹幕数'), number(r[3], '金额'), number(r[4], '进房数')]
        out['viewers'] = clean_rows(row['viewers'], viewer)
    if 'brief' in row and isinstance(row['brief'], dict) and 'brief' not in row['brief']:
        out['brief'] = history_row(row['brief'])
    return out


def state_data(saved, defaults):
    import copy
    import logging
    out = copy.deepcopy(defaults)
    if not isinstance(saved, dict):
        return out
    for key in defaults:
        if key not in saved:
            continue
        value = saved[key]
        try:
            if key in ('session_start', 'live_start', 'last_activity', 'settled_at'):
                out[key] = number(value, key, 0, MAX_TIME)
            elif key in ('was_live', 'summarized', 'dm_segmented'):
                out[key] = boolean(value, key)
            elif key == 'archive_id':
                if not isinstance(value, str) or not SID.fullmatch(value):
                    raise InputError('场次编号无效')
                out[key] = value
            elif key == 'archive_pending':
                out[key] = history_row(value) if value is not None else None
                if out[key] is not None and not all(k in out[key] for k in ('brief', 'end', 'total')):
                    raise InputError('待保存场次不完整')
            elif key == 'settled_dm_count':
                out[key] = integer(value, key, 0, 10**12) if value is not None else None
            elif key in ('flow', 'stats'):
                out[key] = numeric_mapping(value, defaults[key])
            elif key == 'meta':
                out[key] = {k: text(v, k, 256) for k, v in value.items() if k in ('title', 'area')}
            elif key in ('dm', 'enters', 'gifts', 'scs', 'guards'):
                kind = {'dm': 'dm', 'enters': 'enter', 'gifts': 'gift', 'scs': 'sc', 'guards': 'guard'}[key]
                out[key] = clean_rows(value, lambda r: event_row(kind, r))
            elif key == 'sc_read':
                out[key] = value if isinstance(value, list) else []
            elif key == 'songs':
                out[key] = clean_rows(value, queue_row, 200)
            elif key == 'reqs':
                out[key] = clean_rows(value, request_row, 300)
            elif key == 'users':
                out[key] = mapping(value, stored_user)
            elif key == 'gift_stats':
                out[key] = mapping(value, lambda k, r: {'num': number(r['num'], '数量'), 'yuan': number(r['yuan'], '金额')})
            elif key == 'outages':
                out[key] = clean_rows(value, outage_row, 200)
        except (ValueError, TypeError, AttributeError, KeyError):
            out[key] = copy.deepcopy(defaults[key])
            logging.getLogger('xiaowu').warning('旧数据字段 %s 无效，使用默认值', key)
    if 'sc_read' in defaults:
        out['sc_read'] = clean_sc_read(out.get('sc_read'), out.get('scs', []))
    return out


def library_row(name, row):
    if not isinstance(row, dict):
        raise InputError('曲库条目不是对象')
    out = song({'name': name, **{k: row[k] for k in ('artist', 'tags', 'level', 'key', 'backing', 'available', 'note', 'lyrics') if k in row}})
    out.pop('name')
    out['n'] = integer(row.get('n', 0), '演唱次数', 0, 10**12)
    out['last'] = number(row.get('last', 0), '演唱时间', 0, MAX_TIME)
    if 'played' in row:
        if not isinstance(row['played'], list):
            raise InputError('演唱标识无效')
        out['played'] = [text(x, '演唱标识', 80, True) for x in row['played']][-250:]
    return out


def note_row(key, row):
    query_integer(key, 'uid', 1, MAX_UID)
    return {'note': text(row['note'], '备注', 60), 'name': text(row.get('name', ''), '名字', 64),
            't': number(row.get('t', 0), '时间', 0, MAX_TIME)}


def guard_row(key, row):
    query_integer(key, 'uid', 1, MAX_UID)
    return {'level': integer(row['level'], '舰长等级', 1, 3), 'until': number(row['until'], '到期时间', 0, MAX_TIME)}


def room_values(values):
    out = {}
    for key, value in values.items():
        if key in ('bili_ok', 'login_ok', 'bot_admin'):
            out[key] = boolean(value, key)
        elif key == 'live':
            out[key] = integer(value, key, 0, 2)
        elif key in ('uid', 'room_real', 'area_id', 'pop_rank', 'area_rank'):
            out[key] = integer(value, key, 0)
        elif key in ('down_at', 'up_at'):
            out[key] = number(value, key, 0, MAX_TIME)
        elif key in ('watched', 'online', 'likes'):
            out[key] = number(value, key)
        elif key in ('title', 'area', 'watched_text', 'live_time', 'bot_name', 'area_rank_name'):
            out[key] = text(value, key, 64 if key == 'bot_name' else 256)
        elif key in ('cover', 'bot_face'):
            out[key] = url(value)
        elif key == 'top':
            def top(row):
                item = fan_row(row)
                item.update(face=url(row.get('face', '')), guard=integer(row.get('guard', 0), '舰长等级', 0, 3))
                score = row.get('score', 0)
                if isinstance(score, str) and score.isascii() and score.isdecimal() and len(score) <= 15:
                    score = int(score)
                item['score'] = number(score, '高能榜分数')
                return item
            out[key] = clean_rows(value, top, 500)
    return out



def stored_user(key, row):
    item = user_row(row)
    if query_integer(key, 'uid', 1, MAX_UID) != item['uid']:
        raise InputError('观众索引和 uid 不一致')
    return item


def guard_list_row(row):
    out = fan_row(row)
    out.update(face=url(row.get('face', '')), level=integer(row.get('level'), '舰长等级', 1, 3),
               days=number(row.get('days', 0), '陪伴天数', 0, 10**6), until=number(row.get('until', 0), '到期时间', 0, MAX_TIME),
               est=boolean(row.get('est', False), '估算状态'))
    if 'recovered' in row:
        out['recovered'] = boolean(row['recovered'], '补录状态')
    return out
