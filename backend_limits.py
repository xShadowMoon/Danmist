"""管理端 WebSocket 请求的大小与频率检查。"""
import collections
import json
import math


WS_NORMAL_LIMIT = 64 * 1024
WS_IMPORT_LIMIT = 3 * 1024 * 1024


def operation_info(command):
    """只回显短的命令名和请求编号，避免错误响应再发一次大消息。"""
    info = {}
    for name in ('cmd', 'rid'):
        value = command.get(name)
        if isinstance(value, str) and len(value) <= 80:
            info[name] = value
    return info


class OperationError(ValueError):
    def __init__(self, message, command=None):
        super().__init__(message)
        self.info = operation_info(command or {})


def parse_operation(text):
    size = len(text.encode('utf-8'))
    if size > WS_IMPORT_LIMIT:
        raise OperationError('操作内容不能超过 3 MB')
    if text == 'reset':
        return {'cmd': 'reset'}
    try:
        def invalid_constant(value):
            raise ValueError('不支持非有限数值')
        def finite_float(value):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError('数值过大')
            return number
        command = json.loads(text, parse_constant=invalid_constant, parse_float=finite_float)
    except (ValueError, RecursionError):
        raise OperationError('操作格式无效') from None
    if not isinstance(command, dict) or not isinstance(command.get('cmd'), str):
        raise OperationError('操作格式无效')
    # 方案自身仍限 64 KB，额外 1 KB 只容纳命令名、名字和请求编号。
    limit = WS_NORMAL_LIMIT + 1024 if command['cmd'] == 'profile_save' else WS_NORMAL_LIMIT
    if size > limit and command['cmd'] != 'library_import':
        raise OperationError('普通操作不能超过 64 KB', command)
    return command


class OperationRate:
    """每个连接独立滑动计数；拒绝通知也限频，以免堆积发送队列。"""
    def __init__(self):
        self.times = collections.deque()
        self.notice_at = float('-inf')

    def allow(self, now):
        while self.times and now - self.times[0] >= 2:
            self.times.popleft()
        if len(self.times) >= 20:
            return False
        self.times.append(now)
        return True

    def should_notify(self, now):
        if now - self.notice_at < 2:
            return False
        self.notice_at = now
        return True
