"""身份标签（2026-11-26）：改名字 / 颜色、自己的标签、手动标机器人。"""
import os
import tempfile
import unittest

import server
import tags
from test_backend import HubTest


class TagStoreTests(unittest.TestCase):
    def test_config_and_users(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'tags.json')
            t = tags.Tags(p, server.write_json)
            t.set_config({'builtin': {'g3': {'name': '船员', 'short': '船', 'color': '#123456'}}, 'custom': [{'id': 'c1', 'name': '老粉', 'color': ''}]})
            t.set_user(7, ['c1', 'c1', 'nope'])
            t.set_user(8, bot=True)
            again = tags.Tags(p)
            self.assertEqual(again.builtin['g3'], {'name': '船员', 'short': '船', 'color': '#123456'})
            self.assertEqual(again.users, {'7': ['c1']})
            self.assertEqual(again.bots, [8])
            t.set_config({'builtin': {}, 'custom': []})  # 删掉标签，人身上的也没了
            self.assertEqual(t.users, {})

    def test_bad_input(self):
        t = tags.Tags()
        for bad in ({'builtin': {'x': {}}}, {'builtin': {'g1': {'name': '<b>'}}}, {'custom': [{'id': 'c1', 'name': ''}]},
                    {'custom': [{'id': 'zz', 'name': 'a'}]}, {'builtin': {'g1': {'color': 'red'}}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                t.set_config(bad)
        with self.assertRaises(ValueError):
            t.set_user('abc', [])


class TagHubTests(HubTest):
    def test_manual_bot_merges_with_login_bot(self):
        server.set_bots(self.state, [100])
        self.hub.tags.set_user(200, bot=True)
        self.hub.tags_changed()
        self.assertEqual(self.state.bot_uids, [100, 200])
        server.set_bots(self.state, [101])  # 换了登录的号，手动标的还在
        self.assertEqual(self.state.bot_uids, [101, 200])


if __name__ == '__main__':
    unittest.main()
