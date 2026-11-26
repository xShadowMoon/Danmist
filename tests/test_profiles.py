"""设置方案的权限、容量与写入失败回归。"""
import copy
import json
from pathlib import Path
from unittest.mock import patch

from test_backend import HubTest
from profiles import Profiles, validate_profile
import server


class ProfileTests(HubTest):
    def command(self, cmd, **fields):
        return self.hub.profiles.command(cmd, fields, True)

    def test_save_overwrite_get_and_reload(self):
        content = {'朗读': {'开关': True}, '颜色': ['蓝', 12, None]}
        self.command('profile_save', name='唱歌', content=content)
        content['颜色'].append('外部修改')
        row, _ = self.command('profile_get', name='唱歌')
        self.assertEqual(row['profile']['content']['颜色'], ['蓝', 12, None])
        self.command('profile_save', name='唱歌', content={'font': 20})
        again = Profiles(self.hub.profiles.path, server.write_json)
        self.assertEqual(len(again.listing()), 1)
        self.assertEqual(again.data['唱歌']['content'], {'font': 20})
        self.assertNotIn('content', again.listing()[0])
        self.command('profile_delete', name='唱歌')
        self.assertEqual(self.command('profile_list')[0]['profiles'], [])

    def test_profile_count_size_and_field_limits(self):
        for i in range(20):
            self.command('profile_save', name=str(i), content={})
        with self.assertRaisesRegex(ValueError, '20'):
            self.command('profile_save', name='第21个', content={})
        self.command('profile_save', name='0', content={'ok': True})
        for name, content in [('字' * 13, {}), (' ', {}), ('大', {str(i): '雾' * 5000 for i in range(5)}),
                              ('图', {'bg': 'data:image/png;base64,a'}), ('字段', {'x': 'a' * 16385}), ('坏', [])]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_profile(name, content, 0)
        # 上限按 UTF-8 序列化后的整个方案计算，而不是字符数。
        content = {str(i): 'x' * 16000 for i in range(4)}
        validate_profile('边界', content, 0)
        content['pad'] = ''
        length = len(json.dumps({'name': '边界', 'content': content, 'updated_at': 0}, ensure_ascii=False).encode())
        content['pad'] = 'x' * (65536 - length)
        validate_profile('边界', content, 0)
        content['pad'] += 'x'
        with self.assertRaisesRegex(ValueError, '64 KB'):
            validate_profile('边界', content, 0)

    def test_permissions_and_public_filter(self):
        self.command('profile_save', name='私有', content={'secret': '配置'})
        for cmd in ('profile_list', 'profile_get', 'profile_save', 'profile_delete'):
            with self.subTest(cmd=cmd), self.assertRaisesRegex(ValueError, '管理身份'):
                self.hub.profiles.command(cmd, {'name': '私有', 'content': {}}, False)
        self.assertEqual(server.public_view({'profiles': [1], 'nested': {'profile': {'secret': 1}}}), {'nested': {}})

    def test_failed_save_or_delete_keeps_memory_and_disk(self):
        self.command('profile_save', name='旧', content={'size': 16})
        before = copy.deepcopy(self.hub.profiles.data)
        disk = Path(self.hub.profiles.path).read_bytes()
        with patch.object(self.hub.profiles, 'write_json', side_effect=OSError('磁盘满')):
            for cmd, fields in [('profile_save', {'name': '旧', 'content': {}}), ('profile_delete', {'name': '旧'})]:
                with self.assertRaises(OSError):
                    self.command(cmd, **fields)
                self.assertEqual(self.hub.profiles.data, before)
                self.assertEqual(Path(self.hub.profiles.path).read_bytes(), disk)

    def test_corrupt_profile_file_preserved_without_stopping_hub(self):
        path = Path(self.hub.profiles.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{broken', encoding='utf-8')
        reloaded = server.Hub(self.state, self.history)
        with self.assertRaisesRegex(ValueError, '无法读取'):
            reloaded.profiles.command('profile_save', {'name': '新', 'content': {}}, True)
        self.assertEqual(path.read_text(encoding='utf-8'), '{broken')
