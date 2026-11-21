"""管理端设置方案；先落盘再替换内存，磁盘失败不覆盖旧方案。"""
import copy
import json
import math
import logging
import time

MAX_PROFILES = 20
MAX_PROFILE_BYTES = 64 * 1024
MAX_FIELD_BYTES = 16 * 1024


def validate_profile(name, content, updated_at):
    if not isinstance(name, str) or not name.strip() or len(name) > 12:
        raise ValueError('方案名字需要 1 至 12 个字，不能全是空白')
    if isinstance(updated_at, bool) or not isinstance(updated_at, (int, float)) or not math.isfinite(updated_at):
        raise ValueError('方案更新时间无效')
    if not isinstance(content, dict):
        raise ValueError('方案内容必须是 JSON 对象')
    row = {'name': name, 'content': content, 'updated_at': updated_at}
    try:
        encoded = json.dumps(row, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode('utf-8')) > MAX_PROFILE_BYTES:
            raise ValueError('每个设置方案不能超过 64 KB')
        # 逐个检查叶子，避免把背景图的内嵌数据混进同步设置。
        pending = [content]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if any(not isinstance(k, str) for k in value):
                    raise ValueError('方案字段名必须是字符串')
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str):
                if len(value.encode('utf-8')) > MAX_FIELD_BYTES or 'data:image/' in value.lower():
                    raise ValueError('不要上传背景图；单个设置字段不能超过 16 KB')
    except (RecursionError, TypeError, UnicodeError):
        raise ValueError('方案内容不是有效的 JSON 对象') from None
    return copy.deepcopy(row)


class Profiles:
    def __init__(self, path, write_json):
        self.path, self.write_json = path, write_json
        self.data = {}
        self.load_error = ''
        if path:
            try:
                with open(path, encoding='utf-8') as f:
                    rows = json.load(f)
                if not isinstance(rows, dict):
                    raise ValueError('设置方案文件格式无效')
                for name, row in rows.items():
                    try:
                        valid = validate_profile(name, row['content'], row['updated_at'])
                        if len(self.data) < MAX_PROFILES:
                            self.data[name] = valid
                    except (ValueError, TypeError, KeyError, AttributeError):
                        logging.getLogger('xiaowu').warning('跳过无效设置方案')
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
                # 损坏的文件不影响弹幕服务，也不能当成空白覆盖。
                self.load_error = '设置方案文件无法读取，请检查或恢复 profiles.json 后重启'

    def listing(self):
        return [{'name': r['name'], 'updated_at': r['updated_at']}
                for r in sorted(self.data.values(), key=lambda r: (-r['updated_at'], r['name']))]

    def command(self, cmd, c, admin):
        if not admin:
            raise ValueError('此操作需要管理身份')
        if self.load_error:
            raise ValueError(self.load_error)
        if cmd == 'profile_list':
            return {'profiles': self.listing()}, False
        name = c.get('name')
        if not isinstance(name, str):
            raise ValueError('请填写方案名字')
        if cmd == 'profile_get':
            if name not in self.data:
                raise ValueError('设置方案不存在')
            return {'profile': copy.deepcopy(self.data[name])}, False
        updated = dict(self.data)
        if cmd == 'profile_save':
            row = validate_profile(name, c.get('content'), int(time.time()))
            if name not in updated and len(updated) >= MAX_PROFILES:
                raise ValueError('最多保存 20 个设置方案，请先删除一个')
            updated[name] = row
        elif cmd == 'profile_delete':
            if name not in updated:
                raise ValueError('设置方案不存在')
            del updated[name]
        else:
            raise ValueError('未知的设置方案操作')
        if self.path:
            self.write_json(self.path, updated)
        self.data = updated
        return {'profiles': self.listing()}, True
