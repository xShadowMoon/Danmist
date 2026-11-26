import asyncio
import copy
import json
from unittest.mock import Mock, patch

import server
import input_validation as valid
from test_backend import HubTest
from test_viewer import FakeWs


class ScReadTests(HubTest):
    def seed(self):
        self.hub.super_chat(11, 1, '观众一', '', 30, 'SC 一')
        self.hub.super_chat('22', 2, '观众二', '', 30, 'SC 二')
        self.hub.emit_admin = Mock()

    def command(self, sid, read=True):
        return self.hub.sc_read_cmd({'cmd': 'sc_read', 'id': sid, 'read': read})

    def test_read_unread_all_and_string_ids(self):
        self.seed()
        self.command('11')
        self.assertEqual(self.state.sc_read, ['11'])
        self.assertEqual(self.hub.emit_admin.call_args.args, ('sc_read', ['11']))
        self.command(11, False)
        self.assertEqual(self.state.sc_read, [])
        self.hub.sc_read_cmd({'cmd': 'sc_read_all'})
        self.assertEqual(self.state.sc_read, ['11', '22'])
        self.hub.emit_admin.reset_mock()
        self.command(11)
        self.hub.emit_admin.assert_not_called()

    def test_persistence_and_old_file_compatibility(self):
        self.seed()
        self.command(11)
        self.assertEqual(server.State(123).sc_read, ['11'])
        with open(self.state.file, encoding='utf-8') as f:
            old = json.load(f)
        old.pop('sc_read')
        server.write_json(self.state.file, old)
        self.assertEqual(server.State(123).sc_read, [])
        old['sc_read'] = [11, '11', '22', 'missing', None, True]
        server.write_json(self.state.file, old)
        self.assertEqual(server.State(123).sc_read, ['11', '22'])

    def test_missing_id_bad_type_and_write_failure_leave_state_unchanged(self):
        self.seed()
        for sid in ('missing', 99):
            with self.assertRaises(ValueError):
                self.command(sid)
        with self.assertRaises(ValueError):
            self.command(11, 'true')
        with patch.object(server, 'write_json', side_effect=OSError('fake disk error')):
            with self.assertRaises(OSError):
                self.command(11)
        self.assertEqual(self.state.sc_read, [])
        self.hub.emit_admin.assert_not_called()

    def test_reset_session_and_history_have_no_read_state(self):
        self.seed()
        self.command(11)
        self.assertNotIn('sc_read', self.state.summary('下播', self.state.session_start+10))
        self.hub.new_session('手动清零')
        self.assertEqual(self.state.sc_read, [])
        self.assertEqual(server.State(123).sc_read, [])
        self.assertEqual(self.state.snapshot()['sc_read'], [])

    def test_cap_pruning_and_only_present_ids(self):
        self.seed()
        row = self.state.scs[0]
        self.state.scs = [{**row, 'id': n} for n in range(1, 5003)]
        self.hub.sc_read_cmd({'cmd': 'sc_read_all'})
        self.assertEqual(len(self.state.sc_read), 5000)
        with self.assertRaises(ValueError):
            self.command(5002)
        self.state.scs = self.state.scs[1:]
        self.state.save()
        self.assertEqual(len(self.state.sc_read), 4999)
        self.command(5002)
        self.assertEqual(len(self.state.sc_read), 5000)
        self.assertNotIn('1', self.state.sc_read)

    def test_recovered_sc_is_unread_and_existing_duplicate_stays_read(self):
        self.seed()
        self.command(11)
        self.state.sc_read.append('33')
        self.hub.super_chat(33, 3, '补录观众', '', 30, '补录', recovered=True, start=100, end=200)
        self.assertEqual(self.state.sc_read, ['11'])
        self.hub.super_chat('11', 1, '观众一', '', 30, '重复')
        self.assertEqual(self.state.sc_read, ['11'])

    def test_admin_only_snapshots_and_broadcasts(self):
        self.seed()
        async def check():
            first, second, obs, public = FakeWs(), FakeWs(), FakeWs(), FakeWs()
            self.hub.sockets.update({first: True, second: True, obs: False, public: False})
            self.hub.viewers.add(public)
            self.hub.emit_admin = server.Hub.emit_admin.__get__(self.hub)
            self.command(11)
            self.hub.emit_admin('mutes', {'refresh': True})
            await asyncio.sleep(.01)
            for admin in (first, second):
                self.assertEqual([m['type'] for m in admin.sent], ['sc_read', 'mutes'])
            self.assertEqual(obs.sent, [])
            self.assertEqual(public.sent, [])
            await self.hub.push('snapshot', self.state.snapshot())
            self.assertEqual(first.sent[-1]['data']['sc_read'], ['11'])
            self.assertNotIn('sc_read', obs.sent[-1]['data'])
            self.assertNotIn('sc_read', public.sent[-1]['data'])
        asyncio.run(check())
        self.assertEqual(server.public_view({'sc_read': ['11'], 'mutes': {'items': []}, 'nested': [{'sc_read': ['11']}]}), {'nested': [{}]})
        self.assertIsNone(server.viewer_view('sc_read', ['11']))
        self.assertIsNone(server.viewer_view('mutes', {}))
