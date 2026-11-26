"""身份标签（2026-11-26 用户要的）：
- 舰长 / 提督 / 总督 / 房管 / 机器人 / 主播 这几个自带的标签，名字、简称、颜色都能改（空着就是默认的）
- 可以新建自己的标签（比如「老粉」「歌切组」），在观众卡片里给某个人加上
- 可以自己把某个号标成机器人（以前只有连直播间用的那个号算机器人）
存在 data/tags.json。改了马上推给所有网页（标签本来就会显示在弹幕上，普通链接也看得到）。
"""
import json
import os
import re

BUILTIN = {  # 键: (默认名字, 默认简称)
    'g1': ('总督', '总'), 'g2': ('提督', '提'), 'g3': ('舰长', '舰'),
    'admin': ('房管', '房'), 'bot': ('机器人', '机器人'), 'anchor': ('主播', '主播'),
}
CUSTOM_MAX = 20
USERS_MAX = 3000
BOTS_MAX = 50
COLOR = re.compile(r'#[0-9a-fA-F]{6}')


def _text(v, name, limit):
    if not isinstance(v, str):
        raise ValueError(f'{name}要是文字')
    v = v.strip()
    if len(v) > limit or any(c in v for c in '<>"\'&'):
        raise ValueError(f'{name}最多 {limit} 个字，不能有 < > " \' &')
    return v


def _color(v):
    v = str(v or '').strip()
    if v and not COLOR.fullmatch(v):
        raise ValueError('颜色要写成 #rrggbb')
    return v.lower()


def _uid(v):
    if isinstance(v, bool) or not isinstance(v, (int, str)) or not re.fullmatch(r'\d{1,20}', str(v)):
        raise ValueError('观众 uid 不对')
    return int(v)


def clean_config(c):
    """设置里改的那部分：自带标签的名字 / 简称 / 颜色，自己的标签列表"""
    if not isinstance(c, dict):
        raise ValueError('标签设置格式不对')
    builtin = {}
    for k, row in (c.get('builtin') or {}).items():
        if k not in BUILTIN or not isinstance(row, dict) or set(row) - {'name', 'short', 'color'}:
            raise ValueError('自带标签格式不对')
        builtin[k] = {'name': _text(row.get('name', ''), '标签名字', 6), 'short': _text(row.get('short', ''), '标签简称', 4),
                      'color': _color(row.get('color'))}
    custom, seen = [], set()
    rows = c.get('custom') or []
    if not isinstance(rows, list) or len(rows) > CUSTOM_MAX:
        raise ValueError(f'自己的标签最多 {CUSTOM_MAX} 个')
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'id', 'name', 'color'}:
            raise ValueError('标签格式不对')
        tid = str(row.get('id') or '')
        if not re.fullmatch(r'c[0-9a-z]{1,12}', tid) or tid in seen:
            raise ValueError('标签编号不对')
        name = _text(row.get('name', ''), '标签名字', 6)
        if not name:
            raise ValueError('标签要有名字')
        seen.add(tid)
        custom.append({'id': tid, 'name': name, 'color': _color(row.get('color'))})
    return {'builtin': builtin, 'custom': custom}


class Tags:
    def __init__(self, path=None, write_json=None):
        self.path, self.write_json = path, write_json
        self.builtin, self.custom, self.users, self.bots = {}, [], {}, []
        if path and os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    d = json.load(f)
                c = clean_config({'builtin': d.get('builtin') or {}, 'custom': d.get('custom') or []})
                self.builtin, self.custom = c['builtin'], c['custom']
                ids = {t['id'] for t in self.custom}
                for uid, tl in list((d.get('users') or {}).items())[:USERS_MAX]:
                    tl = [t for t in (tl or []) if t in ids]
                    if tl and re.fullmatch(r'\d{1,20}', str(uid)):
                        self.users[str(uid)] = tl
                self.bots = [_uid(u) for u in (d.get('bots') or [])][:BOTS_MAX]
            except (OSError, ValueError, TypeError, AttributeError):
                pass

    def view(self):
        return {'builtin': self.builtin, 'custom': self.custom, 'users': self.users, 'bots': self.bots}

    def save(self):
        if self.path and self.write_json:
            self.write_json(self.path, self.view())

    def set_config(self, c):
        c = clean_config(c)
        self.builtin, self.custom = c['builtin'], c['custom']
        ids = {t['id'] for t in self.custom}
        # 删掉的标签，从每个人身上也去掉
        self.users = {u: [t for t in tl if t in ids] for u, tl in self.users.items()}
        self.users = {u: tl for u, tl in self.users.items() if tl}
        self.save()

    def set_user(self, uid, tags=None, bot=None):
        uid = _uid(uid)
        if tags is not None:
            if not isinstance(tags, list) or len(tags) > CUSTOM_MAX:
                raise ValueError('标签不对')
            ids = {t['id'] for t in self.custom}
            tl = [t for t in dict.fromkeys(str(x) for x in tags) if t in ids]
            if tl:
                if str(uid) not in self.users and len(self.users) >= USERS_MAX:
                    raise ValueError(f'最多给 {USERS_MAX} 个人加标签')
                self.users[str(uid)] = tl
            else:
                self.users.pop(str(uid), None)
        if bot is not None:
            if not isinstance(bot, bool):
                raise ValueError('机器人要是开或关')
            if bot and uid not in self.bots:
                if len(self.bots) >= BOTS_MAX:
                    raise ValueError(f'最多标 {BOTS_MAX} 个机器人')
                self.bots.append(uid)
            elif not bot and uid in self.bots:
                self.bots.remove(uid)
        self.save()
