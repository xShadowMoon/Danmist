"""关键词回应（2026-11-28，参考 DanmuFree）：观众弹幕里有某个词，就自动回一句（发弹幕）或者念出来。

每条规则：几个关键词、回复的话（{name} 换成观众名字）、发弹幕 / 念出来、冷却秒数。
同一条规则冷却时间内只回一次；同一个人同一条规则 2 分钟内只回一次，免得被刷。
规则存在 data/keywords.json。
"""
import json
import os
import time
import uuid

MAX_RULES = 50
PER_USER_CD = 120


def clean_rules(rules):
    """检查网页发来的规则，坏的直接报错（中文原因）"""
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise ValueError(f'最多 {MAX_RULES} 条规则')
    out = []
    for r in rules:
        if not isinstance(r, dict):
            raise ValueError('规则格式不对')
        words = r.get('words')
        if isinstance(words, str):
            words = [w for w in words.replace('，', ',').replace('、', ',').split(',')]
        if not isinstance(words, list):
            raise ValueError('关键词格式不对')
        words = [str(w).strip()[:20] for w in words if str(w).strip()][:10]
        reply = str(r.get('reply') or '').strip()[:40]
        if not words:
            continue  # 没填关键词的那条直接不要
        if not reply:
            raise ValueError(f'「{words[0]}」这条还没写回复的话')
        try:
            cd = int(r.get('cd', 30))
        except (TypeError, ValueError):
            cd = 30
        rid = str(r.get('id') or '')[:16]
        out.append({'id': rid if rid.isalnum() else uuid.uuid4().hex[:8], 'words': words, 'exact': bool(r.get('exact')),
                    'reply': reply, 'say': bool(r.get('say')), 'read': bool(r.get('read', True)),
                    'on': bool(r.get('on', True)), 'cd': max(5, min(3600, cd))})
    return out


class Keywords:
    def __init__(self, path, write_json):
        self.path, self.write_json = path, write_json
        self.rules = []
        self.last = {}       # 规则 id -> 上次回的时间
        self.last_user = {}  # (规则 id, uid) -> 上次回的时间
        try:
            with open(path, encoding='utf-8') as f:
                self.rules = clean_rules(json.load(f).get('rules', []))
        except (OSError, ValueError, AttributeError):
            self.rules = []

    def set(self, rules):
        self.rules = clean_rules(rules)
        if self.path:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self.write_json(self.path, {'rules': self.rules})
        return self.rules

    def match(self, item, now=None):
        """这条弹幕触发了哪些规则：[(规则, 要说的话)]"""
        now = now or time.time()
        text = str(item.get('text') or '').strip()
        if not text:
            return []
        low = text.lower()
        hits = []
        for r in self.rules:
            if not r['on'] or not (r['say'] or r['read']):
                continue
            ok = any(low == w.lower() for w in r['words']) if r['exact'] else any(w.lower() in low for w in r['words'])
            if not ok:
                continue
            uk = (r['id'], item.get('uid'))
            if now - self.last.get(r['id'], 0) < r['cd'] or now - self.last_user.get(uk, 0) < PER_USER_CD:
                continue
            self.last[r['id']] = now
            self.last_user[uk] = now
            if len(self.last_user) > 5000:
                self.last_user.clear()
            hits.append((r, r['reply'].replace('{name}', str(item.get('name') or ''))[:40]))
        return hits
