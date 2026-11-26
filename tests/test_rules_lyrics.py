import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from workbench import clean_song


class RulesLyricsTests(unittest.TestCase):
    def setUp(self):
        tests = Path(__file__).resolve().parent
        self.tmp = tempfile.TemporaryDirectory(dir=tests, prefix='rules-')
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(server, 'DIR', self.tmp.name)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(asyncio.set_event_loop, None)
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        asyncio.set_event_loop(self.loop)
        self.state = server.State(373317)
        self.state.room['room_real'] = 373317
        self.hub = server.Hub(self.state, server.History(373317))
        self.hub.emit = lambda *a, **k: None

    def say(self, uid, text, level=20, room=373317, guard=0):
        self.hub.danmaku(uid, f'观众{uid}', '', text, '雾冬' if level else '', level, guard, medal_room=room if level else 0)

    def test_rules_mark_over_and_persist(self):
        self.hub.set_req_rules({'max': 1, 'medal': 10})
        self.say(1, '点歌 晴天')
        self.say(1, '点歌 稻香')                 # 第二首：超过每人 1 首
        self.say(2, '点歌 七里香', level=5)        # 牌子不够
        self.say(3, '点歌 告白气球', level=15, room=999)  # 别人家的牌子
        self.say(4, '点歌 夜曲', level=0, guard=3)  # 舰长不看粉丝牌
        over = {r['song']: r.get('over', '') for r in self.state.reqs}
        self.assertEqual(over['晴天'], '')
        self.assertIn('每人最多 1 首', over['稻香'])
        self.assertIn('粉丝牌不到 10 级', over['七里香'])
        self.assertIn('粉丝牌', over['告白气球'])
        self.assertEqual(over['夜曲'], '')
        # 重新读文件还在
        hub2 = server.Hub(self.state, server.History(373317))
        self.assertEqual(hub2.req_rules, {'max': 1, 'medal': 10})
        self.assertEqual(server.clean_rules({'max': 'x', 'medal': 999}), {'max': 0, 'medal': 40})

    def test_over_request_not_linked_to_queue(self):
        self.hub.set_req_rules({'max': 0, 'medal': 30})
        self.say(1, '点歌 晴天', level=5)
        self.hub.song_cmd('song_add', text='晴天')
        r = self.state.reqs[0]
        self.assertTrue(r.get('over'))
        self.assertNotIn('queued_id', r)

    def test_lyrics_kept_when_import_has_no_column(self):
        self.assertNotIn('lyrics', clean_song({'name': '晴天'}))
        self.assertEqual(clean_song({'name': '晴天', 'lyrics': ' 故事的小黄花 '})['lyrics'], '故事的小黄花')
        self.hub.library_cmd('library_save', {'song': {'name': '晴天', 'lyrics': '故事的小黄花'}})
        self.hub.library_cmd('library_import', {'rows': [{'name': '晴天', 'artist': '周杰伦'}]})
        row = next(r for r in self.hub.library_list() if r['name'] == '晴天')
        self.assertEqual(row['lyrics'], '故事的小黄花')
        self.assertEqual(row['artist'], '周杰伦')

    def test_drag_move_before_and_to_end(self):
        self.hub.song_cmd('song_add', text='A\nB\nC\nD')
        ids = {x['name']: x['id'] for x in self.state.songs}
        names = lambda: [x['name'] for x in self.state.songs]
        self.hub.song_cmd('song_move', ids['D'], options={'before': ids['B']})
        self.assertEqual(names(), ['A', 'D', 'B', 'C'])
        self.hub.song_cmd('song_move', ids['A'], options={'before': ''})
        self.assertEqual(names(), ['D', 'B', 'C', 'A'])
        self.hub.song_cmd('song_done', ids['D'], options={'done': True})
        with self.assertRaises(ValueError):
            self.hub.song_cmd('song_move', ids['B'], options={'before': ids['D']})
        with self.assertRaises(ValueError):
            self.hub.song_cmd('song_move', ids['D'], options={'before': ids['B']})


if __name__ == '__main__':
    unittest.main()
