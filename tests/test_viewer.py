import asyncio
import json
import unittest

import server


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send_str(self, body):
        self.sent.append(json.loads(body))


class ViewerTests(unittest.TestCase):
    """普通链接只拿得到挑出来的那一点；管理和 OBS 页面不受影响。"""
    def setUp(self):
        self.addCleanup(asyncio.set_event_loop, None)
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        asyncio.set_event_loop(self.loop)
        self.state = server.State(1)
        self.state.file = None
        self.hub = server.Hub(self.state, server.History(1), persist=False)

    def test_snapshot_only_has_basics(self):
        s = self.state
        s.room.update(title='标题', live=1, watched=99, online=5, uid=7, login_ok=True, top=[{'uid': 1}], room_real=1, bili_ok=True)
        s.dm.append({'t': 1, 'uid': 2, 'name': 'a', 'face': '', 'text': 'hi', 'guard': 0, 'spend': 9})
        s.gifts.append({'id': 'g', 't': 1, 'uid': 2, 'name': 'a', 'face': '', 'gift': '花', 'num': 1, 'yuan': 52, 'guard': 0})
        s.scs.append({'id': 1, 't': 1, 'uid': 2, 'name': 'a', 'face': '', 'price': 30, 'text': 'x', 'guard': 0, 'end': 9})
        s.guards.append({'uid': 2, 'name': 'a', 'level': 3, 'yuan': 198})
        s.enters.append({'uid': 2, 'name': 'a', 'kind': 'enter'})
        s.reqs.append({'id': 'r', 'uid': 2, 'song': '晴天'})
        s.songs.append({'id': 's', 'name': '晴天', 'done': False, 'req_ids': ['r']})
        s.users[2] = {'uid': 2, 'name': 'a', 'spend': 250.0, 'dm': 1, 'last': 1}
        s.flow['gift'] = 52
        v = server.viewer_snapshot(s.snapshot())
        # 2026-11-21 放开：B 站上本来看得到的数字、进房、上舰、观众、点歌都给；钱和管理的东西不给
        self.assertEqual(v['room'], {'title': '标题', 'live': 1, 'room_real': 1, 'bili_ok': True, 'online': 5, 'watched': 99, 'top': [{'uid': 1}], 'uid': 7})
        self.assertEqual(v['scs'][0]['price'], 30)                    # SC 金额留着
        self.assertNotIn('yuan', v['gifts'][0]); self.assertTrue(v['gifts'][0]['big'])  # 礼物不带价格
        self.assertEqual(v['songs'], [{'id': 's', 'name': '晴天', 'done': False}])
        self.assertEqual(v['guards'], [{'uid': 2, 'name': 'a', 'level': 3}])  # 上舰不带价格
        self.assertEqual(v['enters'], [{'uid': 2, 'name': 'a', 'kind': 'enter'}])
        self.assertEqual(v['users'], [{'uid': 2, 'name': 'a', 'dm': 1, 'last': 1}])  # 不带花了多少
        self.assertEqual(v['reqs'], [{'id': 'r', 'uid': 2, 'song': '晴天'}])
        self.assertEqual(v['flow'], {'gift': 0, 'sc': 0, 'guard': 0})
        self.assertNotIn('spend', v['dm'][0])
        text = json.dumps(v, ensure_ascii=False)
        for secret in ('198', '250', 'spend', 'yuan', 'req_ids', 'login_ok'):
            self.assertNotIn(secret, text)

    def test_push_filters_by_connection_kind(self):
        admin, obs, viewer = FakeWs(), FakeWs(), FakeWs()
        self.hub.sockets.update({admin: True, obs: False, viewer: False})
        self.hub.viewers.add(viewer)
        run = self.loop.run_until_complete
        gift = {'item': {'id': 'g', 'uid': 2, 'name': 'a', 'gift': '花', 'num': 1, 'yuan': 0.1}, 'flow': {'gift': 0.1}, 'user': {'uid': 2, 'spend': 0.1}}
        run(self.hub.push('gift', gift))
        run(self.hub.push('guard', {'item': {'uid': 2, 'name': 'a', 'level': 3, 'yuan': 198}, 'flow': {}, 'user': {}}))
        run(self.hub.push('enter', {'uid': 2, 'name': 'a', 'kind': 'enter'}))
        run(self.hub.push('reqs', [{'id': 'r'}]))
        run(self.hub.push('room', {'title': 't', 'live': 1, 'watched': 5}))
        self.assertEqual([m['type'] for m in viewer.sent], ['gift', 'guard', 'enter', 'reqs', 'room'])
        self.assertEqual(viewer.sent[0]['data'], {'item': {'id': 'g', 'uid': 2, 'name': 'a', 'gift': '花', 'num': 1, 'big': False}})
        self.assertEqual(viewer.sent[1]['data'], {'item': {'uid': 2, 'name': 'a', 'level': 3}, 'user': {}})  # 没有价格、没有流水
        self.assertEqual(viewer.sent[4]['data'], {'title': 't', 'live': 1, 'watched': 5})
        self.assertEqual(len(obs.sent), 5)                            # OBS 页面照旧都收得到
        self.assertEqual(obs.sent[0]['data']['item']['yuan'], 0.1)
        self.assertEqual(admin.sent[0]['data']['flow'], {'gift': 0.1})

    def test_unknown_kinds_are_not_sent(self):
        for kind in ('req_rules', 'history', 'notes', 'songbook', 'library', 'profiles', 'gift_thanked', 'sc_read', 'mutes', 'tpre', 'warn', 'something_new'):
            self.assertIsNone(server.viewer_view(kind, {}), kind)

    def test_xrooms_list_and_switch(self):
        h = self.hub
        h.xrooms_set({'open': True, 'rooms': [{'room': 10798439, 'name': 'b'}]})  # 2026-11-26 合并：默认名单是空的，先放一个
        self.assertTrue(h.xroom_allowed(10798439))
        h.xrooms_set({'open': True, 'rooms': [{'room': 5, 'name': 'a'}]})
        self.assertTrue(h.xroom_allowed(5)); self.assertFalse(h.xroom_allowed(10798439))
        h.xrooms_set({'open': False, 'rooms': [{'room': 5, 'name': 'a'}]})
        self.assertFalse(h.xroom_allowed(5))                         # 关掉以后谁都切不了
        self.assertEqual(server.viewer_view('xrooms', h.xrooms), {'open': False, 'rooms': []})  # 关着的时候普通链接连名单都看不到
        with self.assertRaises(ValueError):
            h.xrooms_set({'open': True, 'rooms': [{'room': i} for i in range(1, 12)]})  # 最多 10 个


class ObsViewTests(unittest.TestCase):
    """OBS 网址没开「显示价格」：礼物、上舰不带价格，只说大不大、够不够最低价（2026-11-21）。"""
    def test_gift_and_guard_without_price(self):
        g = server.obs_view('gift', {'item': {'id': 'g', 'gift': '花', 'yuan': 52}}, 10)
        self.assertEqual(g['item'], {'id': 'g', 'gift': '花', 'big': True, 'gm_ok': True})
        g = server.obs_view('gift', {'item': {'id': 'g', 'yuan': 0.1}}, 1)
        self.assertEqual((g['item']['big'], g['item']['gm_ok']), (False, False))
        self.assertNotIn('yuan', server.obs_view('guard', {'item': {'level': 3, 'yuan': 198}})['item'])
        snap = server.obs_view('snapshot', {'gifts': [{'yuan': 5}], 'guards': [{'yuan': 198}], 'dm': [1]})
        self.assertNotIn('198', str(snap)); self.assertEqual(snap['dm'], [1])
        self.assertEqual(server.obs_view('dm', {'text': 'x'}), {'text': 'x'})


if __name__ == '__main__':
    unittest.main()
