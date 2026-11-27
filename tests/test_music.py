import asyncio
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import music  # noqa: E402


def svc():
    async def make():
        return music.MusicService('.', False, lambda p, d: None, logging.getLogger('t'), lambda k, d: None, lambda k, d: None)
    return asyncio.run(make())


def dm(uid=1, guard=0, medal='', level=0, room=0, wealth=0):
    return {'uid': uid, 'name': 'n', 'guard': guard, 'medal': medal, 'medal_level': level, 'medal_room': room, 'wealth': wealth}


class MusicRulesTests(unittest.TestCase):
    def test_clean_rules_rejects_bad_values(self):
        r = music.clean_rules({'guard': 3, 'medal': 10, 'skip': 'req'}, music.DEFAULTS)
        self.assertEqual((r['guard'], r['medal'], r['skip']), (3, 10, 'req'))
        for bad in ({'guard': 5}, {'skip': 'all'}, {'on': 1}, {'medal': -1}, {'src': 'spotify'}):
            with self.assertRaises(ValueError):
                music.clean_rules(bad, music.DEFAULTS)

    def test_check_follows_the_rules(self):
        m = svc()
        m.rules.update(guard=3)
        self.assertEqual(m.check(dm(), 100, False), '要舰长以上')
        self.assertEqual(m.check(dm(guard=3), 100, False), '')
        m.rules.update(guard=0, medal=10)
        self.assertIn('粉丝牌', m.check(dm(medal='x', level=5, room=100), 100, False))
        self.assertIn('粉丝牌', m.check(dm(medal='x', level=20, room=999), 100, False))  # 别家的牌子不算
        self.assertEqual(m.check(dm(medal='x', level=20, room=100), 100, False), '')
        m.rules.update(medal=0, wealth=20)
        self.assertIn('荣耀', m.check(dm(wealth=5), 100, False))
        m.rules.update(wealth=0, follow=True)
        self.assertEqual(m.check(dm(), 100, False), '要先关注主播')
        self.assertEqual(m.check(dm(), 100, True), '')
        m.rules.update(follow=False, max=1)
        m.queue.append({'uid': 1, 'state': 'ok'})
        self.assertIn('最多', m.check(dm(), 100, False))

    def test_skip_by_danmaku(self):
        m = svc()
        m.queue = [{'id': 'a', 'uid': 7, 'state': 'play', 'start': 0, 'dur': 100}]
        m.rules['skip'] = 'host'
        self.assertFalse(m.skip_by(dm(uid=7)))
        m.rules['skip'] = 'req'
        self.assertFalse(m.skip_by(dm(uid=8)))
        self.assertTrue(m.skip_by(dm(uid=7)))
        self.assertEqual(m.queue[0]['state'], 'skip')


if __name__ == '__main__':
    unittest.main()


class FakeProvider:
    """不联网的假音乐平台（2026-11-26 点歌改版的测试用）"""
    def __init__(self, songs, playable=True):
        self.songs, self.playable = songs, playable

    async def search(self, q, n=8):
        return [dict(s) for s in self.songs]

    async def url(self, sid):
        return 'https://x/y.mp3' if self.playable else ''

    async def detail(self, song):
        song['cover'] = ''

    async def playlist(self, pid):
        return [dict(s) for s in self.songs]


SONGS = [{'src': '163', 'sid': '1', 'title': '晴天', 'artist': '翻唱的人', 'dur': 200, 'cover': ''},
         {'src': '163', 'sid': '2', 'title': '晴天', 'artist': '周杰伦', 'dur': 269, 'cover': ''}]


class MusicV2Tests(unittest.TestCase):
    """点歌姬：自动回一句、取消点歌、换版本、主播自己加、空闲时放"""
    def run_async(self, coro):
        return asyncio.run(coro)

    def make(self):
        m = svc()
        m.providers['163'] = FakeProvider(SONGS)
        said = []

        async def say(text, uid, dmid, name):
            said.append(text)
        m.say = say
        m.rules.update(on=True, reply=True, max=0)
        return m, said

    def test_request_replies_and_cancel(self):
        m, said = self.make()

        async def go():
            await m.request(dm(uid=5), '晴天', 0, True)
            await m.request(dm(uid=6), '晴天 - 周杰伦', 0, True)
            await asyncio.sleep(0)
            m.cancel_by(dm(uid=5))
            m.cancel_by(dm(uid=9))
            await asyncio.sleep(0)
        self.run_async(go())
        self.assertTrue(said[0].startswith('已点晴天'))
        self.assertIn('已取消晴天', said)
        self.assertIn('你没有排着的歌', said)
        self.assertEqual([x['state'] for x in m.queue], ['skip', 'ok'])
        self.assertEqual(m.queue[1]['artist'], '周杰伦')  # 写了歌手就挑对的那首
        self.assertTrue(all(len(s) <= 20 for s in said))

    def test_reply_off_says_nothing(self):
        m, said = self.make()
        m.rules['reply'] = False
        self.run_async(m.request(dm(uid=5), '晴天', 0, True))
        self.assertEqual(said, [])

    def test_host_add_skips_rules_and_swap_version(self):
        m, said = self.make()
        m.rules.update(guard=1, need_ok=True)

        async def go():
            await m.request({'uid': 0, 'name': '主播'}, '晴天', 0, True, host=True)
            it = m.queue[0]
            alts = await m.alternatives(it['id'])
            msg = await m.swap(it['id'], '2')
            return it, alts, msg
        it, alts, msg = self.run_async(go())
        self.assertEqual(it['state'], 'ok')  # 主播加的不看规则、不用同意
        self.assertEqual([a['sid'] for a in alts], ['1', '2'])
        self.assertEqual((it['sid'], it['artist']), ('2', '周杰伦'))
        self.assertIn('周杰伦', msg)
        self.assertEqual(said, [])  # 主播自己加的不回
        with self.assertRaises(ValueError):
            self.run_async(m.swap(it['id'], '999'))

    def test_idle_pick_from_playlist_and_library(self):
        m, said = self.make()
        m.rules.update(idle='list', idle_list='123')
        s = self.run_async(m.pick_idle())
        self.assertIn(s['sid'], ('1', '2'))
        m.rules.update(idle='lib')
        m.idle_names = lambda: [('晴天', '周杰伦')]
        s = self.run_async(m.pick_idle())
        self.assertEqual(s['sid'], '2')

    def test_idle_rules_and_playlist_link(self):
        r = music.clean_rules({'idle': 'list', 'idle_list': 'https://music.163.com/#/playlist?id=24381616&userid=1', 'vol': 40, 'reply': True}, music.DEFAULTS)
        self.assertEqual((r['idle'], r['idle_list'], r['vol'], r['reply']), ('list', '24381616', 40, True))
        for bad in ({'idle': 'radio'}, {'idle_list': 'https://example.com/x'}, {'vol': 101}):
            with self.assertRaises(ValueError):
                music.clean_rules(bad, music.DEFAULTS)
