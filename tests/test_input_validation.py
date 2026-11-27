"""每个现有命令都有坏输入；同时验证大批量正常使用与旧数据局部损坏。"""
import copy
import json
import time
from pathlib import Path

import input_validation as valid
import server
from backend_limits import OperationError, parse_operation
from test_backend import HubTest


BAD_COMMANDS = {
    'mute_list': {'acct': []}, 'unmute': {'id': '../bad'},
    'sc_read': {'id': '1', 'read': 'true'}, 'sc_read_all': {'id': 1},
    'admin_link_list': {'extra': True}, 'admin_link_create': {'days': 2},
    'admin_link_revoke': {'id': '../bad'}, 'admin_link_rotate': {'name': '字' * 13},
    'reset': {'rid': []}, 'obs_test': {'rid': 123}, 'areas': {'rid': {}}, 'acct_qr': {'rid': False},
    'profile_list': {'rid': []}, 'profile_get': {'name': []}, 'profile_delete': {'name': '字' * 13},
    'profile_save': {'name': '方案', 'content': []},
    'song_add': {'text': ['晴天']}, 'song_done': {'id': 's1', 'done': 'true'}, 'song_del': {},
    'song_clear': {'id': 'unknown'}, 'song_now': {'id': []}, 'song_next': {'expected_now': False},
    'song_move': {'id': 's1', 'before': []},
    'library_save': {'song': {'name': ['歌']}}, 'library_import': {'rows': {}}, 'library_delete': {'name': ''},
    'req_rules': {'max': True}, 'req_done': {'id': []}, 'req_del': {'id': 'x', 'kind': []}, 'req_clear': {},
    'note_set': {'uid': 1, 'name': '观众', 'text': ['备注']}, 'say': {'text': '字' * 41},
    'mute': {'uid': -1}, 'room_edit': {'acct': 'a' * 32, 'area_id': '123'},
    'acct_poll': {'key': []}, 'acct_info': {'acct': 123}, 'acct_logout': {}, 'acct_connect': {'acct': 5}, 'acct_guest': {'x': 1},
    'gift_thank': {'id': [], 'done': True}, 'tpre_set': {'list': [{'title': '字' * 41}]},
    'xrooms_set': {'open': True, 'rooms': [{'room': i} for i in range(1, 12)]},
    'live_start': {'acct': 'a' * 32, 'area_id': '371'}, 'live_stop': {},
    'admin_link_open_del': {'id': 'a' * 32, 't': 'x'},
    'news_get': {'rid': []}, 'news_set': {'acct': 'a' * 32, 'text': '字' * 61},
    # 2026-11-26 补上后来加的命令（手机打开、桌面版、点歌直接放、其他平台、抖音窗口）
    'lan_set': {'on': 'yes'}, 'make_shortcut': {'extra': 1}, 'update_download': {'extra': 1}, 'update_restart': {'extra': 1},
    'open_mode': {'mode': 'x'}, 'music_cookie': {'src': 'x', 'cookie': 'a'}, 'music_del': {'id': []}, 'music_logout': {'src': 'x'},
    'music_next': {'extra': 1}, 'music_ok': {'id': []}, 'music_poll': {'src': '163', 'key': []}, 'music_qr': {'src': 'x'},
    'music_rules': {'max': 'x'}, 'music_top': {'id': ''}, 'plat_set': {'rooms': 'x'},
    'music_vol': {'vol': 101}, 'music_add': {'text': ''}, 'music_alts': {'id': ''}, 'music_swap': {'id': 'a', 'sid': '..'},
    'plat_show': {'plat': 'douyu', 'room': '1', 'show': True},
    'tags_set': {'custom': [{'id': 'x', 'name': 'a'}]}, 'tag_user': {'uid': 'abc'}, 'room_set': {'plat': 'x', 'room': 1},
}


class InputTests(HubTest):
    def test_every_command_rejects_bad_input(self):
        self.assertEqual(set(BAD_COMMANDS), set(valid.COMMAND_FIELDS))
        for cmd, data in BAD_COMMANDS.items():
            with self.subTest(cmd=cmd), self.assertRaises(ValueError):
                valid.validate_command({'cmd': cmd, **data}, server.clean_rules)

    def test_large_normal_commands_still_work(self):
        rows = [{'name': f'歌{i}', 'lyrics': '歌词' * 4000 if i == 0 else '', 'tags': '中文,流行'} for i in range(3000)]
        c = {'cmd': 'library_import', 'rows': rows}
        valid.validate_command(parse_operation(json.dumps(c, ensure_ascii=False)), server.clean_rules)
        self.hub.library_cmd('library_import', c)
        self.assertEqual(len(self.hub.songbook), 3000)
        names = '\n'.join('歌' + str(i) + '字' * 75 for i in range(50))
        valid.validate_command({'cmd': 'song_add', 'text': names}, server.clean_rules)
        self.hub.song_cmd('song_add', text=names)
        first, last = self.state.songs[0]['id'], self.state.songs[-1]['id']
        c = {'cmd': 'song_move', 'id': last, 'before': first}
        valid.validate_command(c, server.clean_rules)
        self.hub.song_cmd('song_move', last, options=c)
        self.assertEqual(self.state.songs[0]['id'], last)
        valid.validate_command({'cmd': 'song_move', 'id': first, 'before': ''}, server.clean_rules)
        valid.validate_command({'cmd': 'song_done', 'id': first, 'text': '', 'req_id': '', 'done': True}, server.clean_rules)
        content = {str(i): 'x' * 16000 for i in range(4)}
        valid.validate_command({'cmd': 'profile_save', 'name': '大方案', 'content': content}, server.clean_rules)

    def test_http_bad_numbers_ids_and_image_host(self):
        cases = [('dm_older', {'uid': 'x'}, {}), ('dm_older', {'before': '-1'}, {}), ('dm_older', {'limit': '501'}, {}),
                 ('dm_older', {'q': '字' * 501}, {}), ('viewer_info', {}, {'uid': '1.5'}),
                 ('hist_get', {}, {'sid': '../x'}), ('hist_dm', {}, {'sid': 'invalid'}),
                 ('hist_delete', {}, {'sid': 'invalid'}), ('img_proxy', {'u': 'https://i0.hdslb.com.evil.invalid/x'}, {}),
                 ('img_proxy', {'u': 'https://secret@i0.hdslb.com/x'}, {})]
        for kind, q, match in cases:
            with self.subTest(kind=kind, q=q), self.assertRaises(valid.InputError):
                valid.validate_http(kind, q, match)
        self.assertEqual(valid.validate_http('dm_older', {'limit': '500', 'before': '0'}, {})['limit'], 500)
        self.assertEqual(valid.validate_http('viewer_info', {}, {'uid': '123'})['uid'], 123)

    def test_bad_live_messages_leave_state_unchanged(self):
        before = copy.deepcopy(self.state.snapshot())
        self.hub.danmaku(1, ['坏名字'], '', '你好')
        self.hub.danmaku(1, '名字', '', '字' * 501)
        self.hub.enter(1, '名字', '', kind=[])
        self.hub.gift(1, '名字', '', '礼物', -1, 1)
        self.hub.super_chat(1, 1, '名字', '', float('nan'), '你好')
        self.hub.guard_buy(1, '名字', 99, 1, 198)
        self.hub.room_update(watched=[])
        self.assertEqual(self.state.snapshot(), before)
        self.hub.danmaku(1, '名' * 64, '', '字' * 500)
        self.assertEqual(len(self.state.dm), 1)

    def test_corrupt_state_keeps_good_rows_and_starts(self):
        self.hub.danmaku(1, '观众', '', '保留这条')
        self.hub.song_cmd('song_add', text='保留歌曲')
        self.state.save()
        path = Path(self.state.file)
        saved = json.loads(path.read_text(encoding='utf-8'))
        saved['dm'].extend([None, {'uid': [], 'text': 12}])
        saved['songs'].extend([False, {'name': ['坏歌']}])
        saved['users']['bad'] = {'uid': 2, 'name': '索引不对'}
        saved['stats']['likes'] = 'bad'
        saved['flow']['gift'] = float('nan')
        saved['outages'] = [{'down_at': 100, 'up_at': 200}, {'down_at': [], 'up_at': 1}]
        server.write_json(str(path), saved)
        loaded = server.State(123)
        self.assertEqual([r['text'] for r in loaded.dm], ['保留这条'])
        self.assertEqual([r['name'] for r in loaded.songs], ['保留歌曲'])
        self.assertNotIn('bad', loaded.users)
        self.assertEqual(loaded.flow['gift'], 0)
        self.assertEqual(len(loaded.outages), 1)
        json.dumps(loaded.snapshot(), allow_nan=False)

    def test_mixed_library_notes_profiles_and_history(self):
        data = self.root / 'data'
        server.write_json(str(data / 'songbook.json'), {'好歌': {'n': 1, 'last': 1}, '坏歌': {'artist': []}})
        server.write_json(str(data / 'notes.json'), {'1': {'name': '观众', 'note': '好的', 't': 1}, '2': []})
        server.write_json(str(data / 'profiles.json'), {'好方案': {'content': {'font': 18}, 'updated_at': 1}, '坏方案': []})
        hub = server.Hub(self.state, self.history)
        self.assertEqual(list(hub.songbook), ['好歌'])
        self.assertEqual(list(hub.notes.data), ['1'])
        self.assertEqual(hub.profiles.listing()[0]['name'], '好方案')
        sid = self.state.archive_id
        row = {'id': sid, 'start': 1, 'end': 2, 'scs': [None], 'viewers': [[1, '观众', 1, 0, 1], []]}
        server.write_json(str(Path(self.history.dir) / (sid + '.json')), row)
        server.write_json(self.history.index_file, [{'id': sid, 'start': 1}, {'id': '../bad', 'start': 'oops'}, None])
        self.assertEqual(len(self.history.list()), 1)
        self.assertEqual(self.history.get(sid)['scs'], [])
        self.assertEqual(len(self.history.get(sid)['viewers']), 1)

    def test_nonfinite_json_and_missing_required_fields(self):
        for value in ('NaN', 'Infinity', '1e999'):
            with self.assertRaises(OperationError):
                parse_operation('{"cmd":"req_rules","max":' + value + '}')
        with self.assertRaises(ValueError):
            valid.validate_command({'cmd': 'library_save', 'song': {'name': '正常', 'lyrics': '字' * 8001}}, server.clean_rules)
        with self.assertRaises(ValueError):
            valid.validate_command({'cmd': 'song_add', 'text': '\n'.join(['歌'] * 51)}, server.clean_rules)
