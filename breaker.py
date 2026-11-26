"""外部服务连续失败先歇一会（2026-11-26，v1.0 前的加固）：
AI 音色、网易云 / QQ 音乐、B 站名片这些外面的服务，连着失败几次就先停一阵不去问，过一会再试；
又失败就停更久（最多 10 分钟），一成功马上恢复。这样一个服务挂了不会一直卡着排队、刷一屏日志。
"""
import logging
import time

log = logging.getLogger('danmaku')


class Resting(ValueError):
    """正在歇着，这次不去问（算 ValueError：调用的地方本来就把它当成「这次没成功」）"""


class Breaker:
    def __init__(self, name, fails=3, rest=30, max_rest=600, clock=time.monotonic):
        self.name, self.fails, self.rest0, self.max_rest, self.clock = name, fails, rest, max_rest, clock
        self.n, self.rest, self.until = 0, rest, 0.0

    def ready(self):
        return self.clock() >= self.until

    def left(self):
        return max(0, int(self.until - self.clock() + 0.999))

    def check(self):
        if not self.ready():
            raise Resting(f'{self.name}刚才连着出错，先歇 {self.left()} 秒再试')

    def ok(self):
        if self.n or self.rest != self.rest0:
            log.info('%s又好了', self.name)
        self.n, self.rest = 0, self.rest0

    def fail(self):
        self.n += 1
        if self.n >= self.fails:
            self.until = self.clock() + self.rest
            log.warning('%s连着失败 %d 次，先歇 %d 秒', self.name, self.n, self.rest)
            self.n, self.rest = 0, min(self.max_rest, self.rest * 2)
