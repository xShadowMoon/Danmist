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
