"""上舰信息、北京时间补天数、下播合并与感谢状态的离线回归。"""
import copy
import datetime
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import server
import input_validation as valid
from round6_helpers import RoundSixTest, request, run_without_io


class GuardRecordTests(RoundSixTest):
    def toast(self, message, source=0):
        row = SimpleNamespace(source=source, toast_msg=message, uid=7, username='观众',
                              guard_level=3, num=1, price=198000, unit='月')
        server.Handler(self.hub)._on_user_toast_v2(None, row)
        return self.state.guards[-1] if self.state.guards else {}

    def test_open_guard_and_days_saved(self):
        row = self.toast('<%观众%> 开通了舰长，今天是TA陪伴主播的第123天')
        self.assertEqual((row['op'], row['days'], row['yuan']), ('开通', 123, 198))
        self.assertEqual(self.hub.emit.call_args.args[0], 'guard')
        self.assertTrue(self.hub.guard_wake.is_set())

    def test_renew_guard_and_spaced_days(self):
        row = self.toast('续费了舰长，第 456 天')
        self.assertEqual((row['op'], row['days']), ('续费', 456))

    def test_unknown_operation_and_no_days(self):
        row = self.toast('欢迎加入大航海')
        self.assertNotIn('op', row)
        self.assertNotIn('days', row)

    def test_non_numeric_or_absent_days(self):
        for message in ('开通了舰长', '续费了舰长，第很多天', None):
            with self.subTest(message=message):
                self.assertNotIn('days', self.toast(message))

    def test_duplicate_source_ignored(self):
        self.toast('续费，第3天', source=2)
        self.assertEqual(self.state.guards, [])

    def test_guard_buy_drops_invalid_optional_fields(self):
        for days in (0, -1, 100000, '7', None):
            with self.subTest(days=days):
                self.hub.guard_buy(7, '观众', 3, 1, 198, op='未知', days=days)
                self.assertNotIn('op', self.state.guards[-1])
                self.assertNotIn('days', self.state.guards[-1])

    def test_event_row_preserves_good_guard_fields(self):
        row = self.toast('续费，第123天')
        row['days_est'] = True
        cleaned = valid.event_row('guard', row)
        self.assertEqual((cleaned['op'], cleaned['days'], cleaned['days_est']), ('续费', 123, True))

    def test_event_row_keeps_wealth_dim_reply(self):
        # 2026-11-28：重启后读回来的弹幕以前丢了荣耀等级、灰牌子、回复谁
        row = {'t': 1795799673, 'uid': 1, 'name': '观众', 'text': '晚安', 'medal': '雾锁胃', 'medal_level': 20,
               'medal_room': 373317, 'medal_dim': 1, 'wealth': 28, 'reply': '小鱼干', 'i': 1}
        cleaned = valid.event_row('dm', row)
        self.assertEqual((cleaned['wealth'], cleaned['medal_dim'], cleaned['reply']), (28, 1, '小鱼干'))
        bad = valid.event_row('dm', {**row, 'wealth': '28', 'medal_dim': 5, 'reply': 'x' * 100})
        self.assertNotIn('wealth', bad)
        self.assertNotIn('medal_dim', bad)
        self.assertNotIn('reply', bad)
        self.assertEqual(bad['text'], '晚安')

    def test_event_row_rejects_invalid_operation(self):
        row = self.toast('开通，第1天')
        for value in ('未知', '', None, 1, []):
            with self.subTest(value=value), self.assertRaises(valid.InputError):
                valid.event_row('guard', {**row, 'op': value})

    def test_event_row_rejects_invalid_days(self):
        row = self.toast('开通，第1天')
        for value in (0, -1, 100000, '3', True, None):
            with self.subTest(value=value), self.assertRaises(valid.InputError):
                valid.event_row('guard', {**row, 'days': value})

    def test_live_dmid_accepts_only_bounded_alphanumeric(self):
        for dmid in ('abc123', 'a' * 64, '', 'a' * 65, 'bad-id', 42, None):
            with self.subTest(dmid=dmid):
                self.hub.danmaku(7, '观众', '', '你好', dmid=dmid)
                self.assertEqual(self.state.dm[-1].get('dmid'), dmid if dmid in ('abc123', 'a' * 64) else None)

    def test_handler_gets_dmid_from_extra(self):
        row = SimpleNamespace(dm_type=0, extra_dict={'id_str': 'abc123'}, uid=7, uname='观众', face='',
                              msg='你好', medal_name='', medal_level=0, privilege_type=0, admin=0, medal_room_id=0)
        server.Handler(self.hub)._on_danmaku(None, row)
        self.assertEqual(self.state.dm[-1]['dmid'], 'abc123')

    def test_event_row_keeps_good_dmid(self):
        self.hub.danmaku(7, '观众', '', '你好', dmid='abc123')
        self.assertEqual(valid.event_row('dm', self.state.dm[-1])['dmid'], 'abc123')

    def test_stored_bad_dmid_and_days_est_are_dropped(self):
        # 2026-11-21 补上：存档里坏的弹幕编号 / 推算标记只丢这个字段，记录本身留着
        self.hub.danmaku(7, '观众', '', '你好')
        for value in ('bad-id', 'x' * 65, 42, None):
            with self.subTest(value=value):
                row = valid.event_row('dm', {**self.state.dm[-1], 'dmid': value})
                self.assertNotIn('dmid', row)
                self.assertEqual(row['text'], '你好')
        self.assertEqual(valid.event_row('dm', {**self.state.dm[-1], 'dmid': 'abc123'})['dmid'], 'abc123')
        row = self.toast('开通，第1天')
        self.assertNotIn('days_est', valid.event_row('guard', {**row, 'days_est': '坏值'}))
        self.assertIs(valid.event_row('guard', {**row, 'days_est': True})['days_est'], True)


class GuardDaysTests(RoundSixTest):
    def setUp(self):
        super().setUp()
        self.now = int(datetime.datetime(2026, 11, 21, 0, 1, tzinfo=server.BJ).timestamp())
        self.enterContext(patch.object(server.time, 'time', return_value=self.now))
        self.hub.guardlist = [{'uid': 7, 'days': 10}]

    def test_back_calculation(self):
        rows = [{'uid': 7, 't': self.now - 3 * 86400}]
        self.assertTrue(server.complete_guard_days(self.hub, rows))
        self.assertEqual((rows[0]['days'], rows[0]['days_est']), (7, True))

    def test_cross_beijing_midnight_counts_as_day(self):
        rows = [{'uid': 7, 't': self.now - 120}]
        server.complete_guard_days(self.hub, rows)
        self.assertEqual(rows[0]['days'], 9)

    def test_same_beijing_day(self):
        rows = [{'uid': 7, 't': self.now - 30}]
        server.complete_guard_days(self.hub, rows)
        self.assertEqual(rows[0]['days'], 10)

    def test_zero_and_negative_not_filled(self):
        rows = [{'uid': 7, 't': self.now - n * 86400} for n in (10, 11)]
        self.assertFalse(server.complete_guard_days(self.hub, rows))
        self.assertTrue(all('days' not in row for row in rows))

    def test_existing_days_not_changed(self):
        rows = [{'uid': 7, 't': self.now, 'days': 3}]
        before = copy.deepcopy(rows)
        self.assertFalse(server.complete_guard_days(self.hub, rows))
        self.assertEqual(rows, before)

    def test_absent_uid_or_empty_roster_not_filled(self):
        rows = [{'uid': 8, 't': self.now}, None]
        self.assertFalse(server.complete_guard_days(self.hub, rows))
        self.hub.guardlist = []
        self.assertFalse(server.complete_guard_days(self.hub, [{'uid': 7, 't': self.now}]))

    def test_bad_roster_days_and_upper_bound_not_filled(self):
        for days in ('10', 0, -1, 100000):
            with self.subTest(days=days):
                self.hub.guardlist = [{'uid': 7, 'days': days}]
                self.assertFalse(server.complete_guard_days(self.hub, [{'uid': 7, 't': self.now}]))


class OfflineRecordTests(RoundSixTest):
    def save(self, name, value):
        p = self.root / 'data' / 'offline' / str(self.state.room_id) / name
        server.write_json(str(p), value)
        return p

    def listing(self, admin=True):
        response = run_without_io(server.list_offline(request(admin=admin), self.state, self.hub, '', 8390))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        return json.loads(response.text)

    def test_thank_item_kept_in_both_current_and_offline_file(self):
        # 2026-11-21 线上 bug：换场时下播礼物另存进下播记录，本场也还留着一份；点 ✓ 只改了本场那份，页面显示的是文件那份
        g = {'id': 'g9', 'uid': 7, 't': 10, 'gift': '花', 'yuan': 1}
        p = self.save('x.json', {'gifts': [dict(g)]})
        self.state.gifts = [{**g, 'source': '下播'}]
        self.state.save = Mock(return_value=True)
        self.hub.gift_thank_cmd({'id': 'g9', 'done': True})
        self.assertTrue(json.loads(p.read_text(encoding='utf-8'))['gifts'][0].get('thanked'))
        self.assertTrue(self.listing()['gifts'][0].get('thanked'))
        self.hub.gift_thank_cmd({'id': 'g9', 'done': False})
        self.assertFalse(json.loads(p.read_text(encoding='utf-8'))['gifts'][0].get('thanked'))
        self.assertFalse(self.listing()['gifts'][0].get('thanked'))

    def test_old_data_thanked_in_either_copy_counts(self):
        g = {'id': 'g8', 'uid': 7, 't': 10, 'gift': '花', 'yuan': 1}
        self.save('y.json', {'gifts': [dict(g)]})
        self.state.gifts = [{**g, 'source': '下播', 'thanked': True}]
        self.assertTrue(self.listing()['gifts'][0].get('thanked'))

    def test_multiple_files_current_duplicates_sort_totals_and_images(self):
        old = {'id': 'g1', 'uid': 7, 't': 10, 'gift': '花', 'yuan': 1.25}
        self.save('a.json', {'gifts': [old], 'scs': [{'id': 1, 't': 12, 'price': 30}]})
        self.save('b.json', {'gifts': [old, {'id': 'g2', 't': 20, 'gift': '花', 'img': 'keep', 'yuan': 2.5}],
                             'guards': [{'id': 'g1', 'uid': 7, 't': 15, 'yuan': 198}]})
        self.state.gifts = [{**old, 'source': '下播'}, {'id': 'g3', 't': 30, 'yuan': 3.75, 'source': '下播'},
                            {'id': 'live', 't': 40, 'yuan': 999}]
        before = copy.deepcopy(self.state.gifts)
        with patch.dict(server.GIFT_BY_NAME, {'花': ('fake-image', '')}):
            data = self.listing()
        self.assertEqual([g['id'] for g in data['gifts']], ['g3', 'g2', 'g1'])
        self.assertEqual([g['img'] for g in data['gifts']], ['', 'keep', 'fake-image'])
        self.assertEqual(data['flow'], {'gift': 7.5, 'sc': 30, 'guard': 198})
        self.assertEqual(data['total'], 235.5)
        self.assertTrue(all(x['source'] == '下播' for k in ('gifts', 'scs', 'guards') for x in data[k]))
        self.assertEqual(self.state.gifts, before)

    def test_fallback_dedup_uid_time_and_kind(self):
        row = {'uid': 7, 't': 1}
        self.save('a.json', {'gifts': [row, row], 'guards': [row]})
        self.save('b.json', {'gifts': [row]})
        data = self.listing()
        self.assertEqual((len(data['gifts']), len(data['guards'])), (1, 1))

    def test_summarized_unsaved_items_after_cutoff(self):
        self.state.summarized, self.state.settled_at = True, 10
        self.state.scs = [{'id': n, 't': n, 'price': 30} for n in (9, 10, 11)]
        self.assertEqual([r['id'] for r in self.listing()['scs']], [11])

    def test_broken_json_and_non_dict_rows_skipped(self):
        p = self.save('bad.json', {})
        p.write_text('{broken', encoding='utf-8')
        self.save('ok.json', {'gifts': [None, 5, {'id': 'g', 't': 1, 'yuan': 1}]})
        self.assertEqual(self.listing()['total'], 1)

    def test_missing_directory_empty_result(self):
        self.assertEqual(self.listing()['total'], 0)

    def test_public_access_rejected(self):
        with self.assertRaises(server.web.HTTPForbidden):
            self.listing(admin=False)

    def test_days_only_filled_on_output(self):
        now = int(server.time.time())
        original = {'guards': [{'id': 'g', 'uid': 7, 't': now, 'yuan': 198}]}
        p = self.save('a.json', original)
        self.hub.guardlist = [{'uid': 7, 'days': 8}]
        self.assertEqual(self.listing()['guards'][0]['days'], 8)
        self.assertEqual(json.loads(p.read_text(encoding='utf-8')), original)

    def test_valid_json_with_wrong_root_is_skipped(self):
        # 2026-11-21 补上：文件能解析但不是正常的一段记录（比如列表），跳过它，别的照常列
        self.save('array.json', [])
        self.save('ok.json', {'gifts': [{'id': 'g', 'uid': 7, 't': 5, 'gift': '花', 'yuan': 1}]})
        out = self.listing()
        self.assertEqual([x['id'] for x in out['gifts']], ['g'])
        self.save('b-array.json', [{'id': 'g'}])
        self.assertFalse(self.hub.offline_thank('nope', True))

    def test_current_thank_and_cancel_do_not_search_offline(self):
        self.state.gifts = [{'id': 'g'}]
        self.state.save = Mock(return_value=True)
        with patch.object(self.hub, 'offline_thank', side_effect=AssertionError('本场找到后不该查文件')):
            for done in (True, False):
                self.assertEqual(self.hub.gift_thank_cmd({'id': 'g', 'done': done}), '已同步')
                self.assertEqual(bool(self.state.gifts[0].get('thanked')), done)
        self.assertEqual(self.state.save.call_count, 2)
        self.assertEqual(self.hub.emit_admin.call_count, 2)

    def test_offline_thank_and_cancel_write_same_file(self):
        a = self.save('a.json', {'gifts': [{'id': 'other'}]})
        b = self.save('b.json', {'gifts': [{'id': 'g'}], 'scs': [{'id': 1}]})
        first = a.read_bytes()
        with patch.object(server, 'write_json', wraps=server.write_json) as writer:
            for done in (True, False):
                self.assertEqual(self.hub.gift_thank_cmd({'id': 'g', 'done': done}), '已同步')
                self.assertEqual(writer.call_args.args[0], str(b))
                saved = json.loads(b.read_text(encoding='utf-8'))
                self.assertEqual(bool(saved['gifts'][0].get('thanked')), done)
                self.assertEqual(saved['scs'], [{'id': 1}])
        self.assertEqual(a.read_bytes(), first)

    def test_offline_guard_can_be_thanked(self):
        p = self.save('a.json', {'guards': [{'id': 'g'}]})
        self.assertTrue(self.hub.offline_thank('g', True))
        self.assertTrue(json.loads(p.read_text(encoding='utf-8'))['guards'][0]['thanked'])

    def test_thank_missing_id_returns_error_without_emit(self):
        self.assertFalse(self.hub.offline_thank('missing', True))
        with self.assertRaises(ValueError):
            self.hub.gift_thank_cmd({'id': 'missing', 'done': True})
        self.hub.emit_admin.assert_not_called()

    def test_thank_skips_bad_file(self):
        p = self.save('a.json', {})
        p.write_text('{bad', encoding='utf-8')
        self.save('b.json', {'gifts': [{'id': 'g'}]})
        self.assertTrue(self.hub.offline_thank('g', True))

    def test_thank_failed_write_does_not_emit_success(self):
        p = self.save('a.json', {'gifts': [{'id': 'g'}]})
        before = p.read_bytes()
        with patch.object(server, 'write_json', side_effect=OSError('假磁盘失败')):
            with self.assertRaises(OSError):
                self.hub.gift_thank_cmd({'id': 'g', 'done': True})
        self.assertEqual(p.read_bytes(), before)
        self.hub.emit_admin.assert_not_called()


class HistoryGuardDaysTests(RoundSixTest):
    def test_history_response_estimates_days_without_changing_archive(self):
        self.bootstrap()
        sid = self.hub.history.list()[0]['id']
        now = int(server.time.time())
        original = {'id': sid, 'guards': [{'uid': 7, 't': now}]}
        self.hub.guardlist = [{'uid': 7, 'days': 9}]
        req = request()
        req.match_info = {'sid': sid}
        with patch.object(self.hub.history, 'get', return_value=original), \
                patch.object(self.hub.history, 'has_dm', return_value=False):
            response = run_without_io(self.routes['/api/history/{sid}'](req))
        self.assertEqual(json.loads(response.text)['guards'][0]['days'], 9)
        self.assertNotIn('days', original['guards'][0])
