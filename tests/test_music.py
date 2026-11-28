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


class WebLoginTests(unittest.TestCase):
    """弹出官网登录页登录（2026-11-26）：从浏览器的 Cookie 里挑出登录要的"""
    def test_cookie_text(self):
        import music_login as ml
        cs = [{'domain': '.music.163.com', 'name': 'MUSIC_U', 'value': 'abc'}, {'domain': '.music.163.com', 'name': '__csrf', 'value': 'x'},
              {'domain': '.qq.com', 'name': 'uin', 'value': 'o123'}, {'domain': '.y.qq.com', 'name': 'qqmusic_key', 'value': 'K'},
              {'domain': '.evil.com', 'name': 'MUSIC_U', 'value': 'zzz'}]
        self.assertEqual(ml.cookie_text('163', cs), 'MUSIC_U=abc; __csrf=x')
        self.assertEqual(ml.cookie_text('qq', cs), 'uin=o123; qqmusic_key=K')
        self.assertEqual(ml.cookie_text('163', cs[2:4]), '')
        self.assertEqual(ml.cookie_text('qq', cs[:2]), '')


class Music6Tests(unittest.TestCase):
    """借鉴别的点歌姬（2026-11-26）：换平台兜底、指定平台、冷却、拖动排序、B 站视频"""
    def make(self):
        m = svc()
        m.providers['163'] = FakeProvider([], playable=False)
        m.providers['qq'] = FakeProvider([dict(SONGS[1], src='qq', sid='q2')])
        m.rules.update(on=True, max=0)
        return m

    def test_fallback_and_forced_source(self):
        m = self.make()
        s, _ = asyncio.run(m.find('晴天'))
        self.assertEqual(s['src'], 'qq')  # 网易云放不了：去 QQ 找
        m.rules['fallback'] = False
        s, miss = asyncio.run(m.find('晴天'))
        self.assertIsNone(s)
        m.providers['163'] = FakeProvider(SONGS)
        s, _ = asyncio.run(m.find('qq 晴天'))
        self.assertEqual(s['src'], 'qq')
        s, _ = asyncio.run(m.find('网易云 晴天'))
        self.assertEqual(s['src'], '163')

    def test_cooldowns(self):
        m = self.make()
        m.providers['163'] = FakeProvider(SONGS)
        m.rules.update(cd_user=30, cd_song=10)
        asyncio.run(m.request(dm(uid=5), '晴天', 0, True))
        self.assertIn('点太快了', m.check(dm(uid=5), 0, True))
        self.assertEqual(m.check(dm(uid=6), 0, True), '')
        m.played['1'] = __import__('time').time()
        m.queue.clear()
        asyncio.run(m.request(dm(uid=7), '晴天', 0, True))
        self.assertEqual(m.queue[-1]['state'], 'deny')
        self.assertIn('刚放过', m.queue[-1]['why'])

    def test_move(self):
        m = self.make()
        m.queue = [{'id': x, 'uid': 1, 'state': 'ok', 'sid': x} for x in 'abc']
        m.move('c', 'a')
        self.assertEqual([x['id'] for x in m.queue], ['c', 'a', 'b'])
        m.move('c', '')
        self.assertEqual([x['id'] for x in m.queue], ['a', 'b', 'c'])
        with self.assertRaises(ValueError):
            m.move('zz', '')

    def test_bv_pattern(self):
        self.assertEqual(music.BV_RE.search('BV1xx411c7mD 好听').group(1), 'BV1xx411c7mD')
        self.assertEqual(music.BV_RE.search('av170001').group(2), '170001')
        self.assertTrue(music.BV_RE.search('https://b23.tv/abcd123'))
        self.assertIsNone(music.BV_RE.search('晴天 - 周杰伦'))


class OpenQuietTests(unittest.TestCase):
    """叫音乐客户端时要求最小化、不抢前台（2026-11-28）"""

    def test_asks_for_minimized_no_focus(self):
        from unittest import mock
        with mock.patch.object(music.os, 'startfile', create=True) as sf:
            music.open_quiet('orpheus://abc')
        sf.assert_called_once_with('orpheus://abc', 'open', show_cmd=7)

    def test_old_python_falls_back(self):
        from unittest import mock
        calls = []

        def old(uri, *rest, **kw):
            if rest or kw:
                raise TypeError('too many args')
            calls.append(uri)
        with mock.patch.object(music.os, 'startfile', old, create=True):
            music.open_quiet('qqmusic://x')
        self.assertEqual(calls, ['qqmusic://x'])


class ClientControlTests(unittest.TestCase):
    """音乐客户端放歌（2026-11-28）：放一首后叫它真的放起来；点的歌放完叫它暂停；第一次用时提醒放副屏"""

    def test_started_then_stopped(self):
        from unittest import mock
        calls, tips = [], []

        async def fake_run(src, do):
            calls.append((src, do))
            return 'Playing'

        m = svc()

        async def go():
            m.tip = lambda title, text: tips.append(title)
            with mock.patch.object(music.media_ctl, 'run', fake_run), mock.patch.object(music.asyncio, 'sleep', mock.AsyncMock()):
                m.client_started('163')
                m.client_started('163')
                await asyncio.gather(*list(m.bg_tasks))
                m.client_stop()
                await asyncio.gather(*list(m.bg_tasks))
                m.client_stop()  # 已经停了：不再叫
                await asyncio.gather(*list(m.bg_tasks))
        asyncio.run(go())
        self.assertEqual(calls, [('163', 'play'), ('163', 'play'), ('163', 'pause')])
        self.assertEqual(len(tips), 1)
        self.assertEqual(m.app_client, '')
