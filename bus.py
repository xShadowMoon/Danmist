"""事件总线（2026-11-26）：各平台的消息记下来以后在这里发一次，要用的地方订阅。

    hub.bus.on('dm', fn)          # fn(item)：每条弹幕（不管哪个平台）
    hub.bus.on('*', fn)           # fn(kind, item)：所有消息
种类：dm（弹幕）、enter（进房 / 关注 / 分享 / 点赞）、gift（礼物）、sc（醒目留言）、guard（上舰）。
订阅按加的先后跑；一个出错只记日志，后面的照跑。
"""
import collections
import logging

log = logging.getLogger('danmaku')
KINDS = ('dm', 'enter', 'gift', 'sc', 'guard')


class Bus:
    def __init__(self):
        self.subs = collections.defaultdict(list)

    def on(self, kind, fn):
        if kind != '*' and kind not in KINDS:
            raise ValueError(f'没有这种消息：{kind}')
        self.subs[kind].append(fn)
        return fn

    def off(self, kind, fn):
        if fn in self.subs.get(kind, []):
            self.subs[kind].remove(fn)

    def publish(self, kind, item):
        for fn in list(self.subs.get(kind, ())):
            self._call(fn, kind, item)
        for fn in list(self.subs.get('*', ())):
            self._call(fn, kind, item, True)

    @staticmethod
    def _call(fn, kind, item, both=False):
        try:
            fn(kind, item) if both else fn(item)
        except Exception:  # 一个订阅坏了不影响别的
            log.exception('处理 %s 消息的 %s 出错了', kind, getattr(fn, '__name__', fn))
