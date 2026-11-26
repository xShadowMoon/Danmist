import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import server
from admin_links import AdminLinks, DAY
from test_backend import TemporaryDataTest, HubTest


class AdminLinkTests(TemporaryDataTest):
    def make(self, legacy='', now=1000000):
        return AdminLinks(str(self.root / 'data' / 'admin-links.json'), server.write_json, legacy, now)

    def test_create_hash_only_expire_and_list(self):
        links = self.make()
        key, token = links.create('手机', 1, now=1000000)
        self.assertEqual(links.authenticate(token, 1000001), key)
        self.assertIsNone(links.authenticate(token, 1000000 + DAY))
        raw = (self.root / 'data' / 'admin-links.json').read_text(encoding='utf-8')
        self.assertNotIn(token, raw)
        self.assertNotIn('hash', links.listing(key, 1000001)[0])
        self.assertTrue(links.listing(key, 1000001)[0]['current'])

    def test_legacy_revocation_survives_cleanup_and_restart(self):
        links = self.make('fake-old-key')
        key = links.authenticate('fake-old-key', 1000001)
        self.assertTrue(key)
        links.revoke(key, 1000002)
        links.maintain(1000002 + 31 * DAY)
        again = self.make('fake-old-key', 1000002 + 31 * DAY)
        self.assertIsNone(again.authenticate('fake-old-key'))
        self.assertEqual(again.data['links'], [])

    def test_cap_rotate_and_failed_write_are_atomic(self):
        links = self.make()
        tokens = [links.create(now=1000000)[1] for _ in range(10)]
        with self.assertRaises(ValueError):
            links.create(now=1000000)
        with patch.object(links, 'writer', side_effect=OSError):
            with self.assertRaises(OSError):
                links.create(replace=True, now=1000001)
        self.assertTrue(links.authenticate(tokens[0], 1000002))
        key, token = links.create(replace=True, now=1000003)
        self.assertTrue(links.authenticate(token, 1000004))
        self.assertTrue(all(links.authenticate(t, 1000004) is None for t in tokens))
        self.assertEqual(sum(r['active'] for r in links.listing(now=1000004)), 1)

    def test_local_unaffected_cookie_expiry_and_corrupt_store_fail_closed(self):
        links = self.make('fake-old-key')
        request = SimpleNamespace(query={}, cookies={'xwadmin': 'fake-old-key'}, headers={'CF-Connecting-IP': '192.0.2.1'},
                                  remote='127.0.0.1', host='live.shadowcary.com')
        self.assertTrue(server.is_admin(request, links, 8390))
        links.revoke(links.authenticate('fake-old-key'))
        self.assertFalse(server.is_admin(request, links, 8390))
        request.headers, request.host = {}, '127.0.0.1:8390'
        self.assertTrue(server.is_admin(request, links, 8390))
        (self.root / 'data' / 'admin-links.json').write_text('{bad', encoding='utf-8')
        broken = self.make('fake-old-key')
        self.assertIsNone(broken.authenticate('fake-old-key'))
        self.assertTrue(server.is_admin(request, broken, 8390))

    def test_failed_legacy_migration_still_allows_local_access(self):
        with patch.object(server, 'write_json', side_effect=OSError):
            links = self.make('fake-old-key')
        req = SimpleNamespace(query={}, cookies={}, headers={}, remote='127.0.0.1', host='127.0.0.1:8390')
        self.assertTrue(server.is_admin(req, links, 8390))
        self.assertIsNone(links.authenticate('fake-old-key'))


    def test_admin_secrets_redacted_from_logs_exceptions_and_journal(self):
        import logging
        import sys
        from admin_links import AdminSafeFormatter
        from error_journal import ErrorJournal
        formatter = AdminSafeFormatter('%(message)s')
        journal = ErrorJournal(None, None, lambda *a: None)
        for text in ('GET /?admin=SECRET&x=1', 'Cookie: xwadmin=SECRET;', '{"admin_key":"SECRET"}'):
            record = logging.LogRecord('test', logging.ERROR, 'test.py', 1, text, (), None)
            self.assertNotIn('SECRET', formatter.format(record))
            journal.emit(record)
        try:
            raise ValueError('request /?admin=SECRET')
        except ValueError:
            record = logging.LogRecord('test', logging.ERROR, 'test.py', 1, '失败', (), sys.exc_info())
            self.assertNotIn('SECRET', formatter.format(record))
            journal.emit(record)
        self.assertNotIn('SECRET', json.dumps(journal.rows))


    def test_generated_link_keeps_optional_site_access_key(self):
        from urllib.parse import urlsplit, parse_qs
        links = self.make()
        reply = links.command({'cmd': 'admin_link_create', 'name': '手机'}, 'https://example.invalid', access_key='fake-site-key')
        query = parse_qs(urlsplit(reply['url']).query)
        self.assertEqual(query['key'], ['fake-site-key'])
        self.assertEqual(links.authenticate(query['admin'][0]), reply['id'])
        self.assertNotIn(reply['url'], json.dumps(links.data))



class ConnectedAdminTests(HubTest):
    def test_revoke_removes_connected_permission_before_close(self):
        links = AdminLinks(None, server.write_json)
        key, token = links.create()
        self.hub.admin_links = links
        ws, local = AsyncMock(), AsyncMock()
        self.hub.sockets.update({ws: True, local: True})
        self.hub.link_sockets[ws] = key
        links.revoke(key)
        self.assertFalse(self.hub.socket_allowed(ws))
        closed = self.hub.invalidate_links()
        self.assertNotIn(ws, self.hub.sockets)
        self.assertTrue(self.hub.socket_allowed(local))
        asyncio.run(self.hub.close_links(closed))
        ws.close.assert_awaited_once()

    def test_expired_connection_cannot_receive_private_push(self):
        links = AdminLinks(None, server.write_json)
        key, _ = links.create(days=1, now=1000000)
        self.hub.admin_links = links
        ws = AsyncMock()
        self.hub.sockets[ws] = True
        self.hub.link_sockets[ws] = key
        asyncio.run(self.hub.push('notes', {'private': True}))
        ws.send_str.assert_not_awaited()
        self.assertEqual(self.hub.invalidate_links(), [ws])
