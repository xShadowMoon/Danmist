"""所有通知发送均用假的函数，不访问 Discord。"""
import asyncio
import datetime as dt
import logging
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import server
from error_journal import ErrorJournal, redact
from test_backend import TemporaryDataTest


class JournalTests(TemporaryDataTest):
    def journal(self):
        obj = ErrorJournal(str(self.root / 'errors.json'), str(self.root / 'report.json'), server.write_json)
        self.addCleanup(lambda: setattr(obj, 'path', None))
        self.addCleanup(lambda: setattr(obj, 'marker', None))
        return obj

    def test_merge_expire_and_record_limit(self):
        journal = self.journal()
        now = time.time()
        journal.add('WARNING', '连接失败', '网络', now)
        journal.add('WARNING', '连接失败', '网络', now)
        self.assertEqual(journal.rows[0]['count'], 2)
        with patch('error_journal.MAX_ERRORS', 3):
            for i in range(4):
                journal.add('ERROR', str(i), '测试', now)
            self.assertEqual(len(journal.rows), 3)
        journal.prune(now + 8 * 86400)
        self.assertFalse(journal.rows)

    def test_redaction_before_disk_and_report(self):
        journal = self.journal()
        secret = 'https://discord.com/api/webhooks/123/SECRET?key=ABC Cookie: SESSDATA=DEF; bili_jct=GHI'
        journal.add('ERROR', secret, 'worker?token=JKL')
        journal.flush()
        text = (self.root / 'errors.json').read_text(encoding='utf-8')
        for value in ('SECRET', 'ABC', 'DEF', 'GHI', 'JKL'):
            self.assertNotIn(value, text)
        for text in ('{"token":"SECRET"}', "password='SECRET'", 'Authorization: Bearer SECRET', 'access_token=SECRET'):
            self.assertNotIn('SECRET', redact(text))

    def test_daily_no_errors_failure_retry_and_restart_dedup(self):
        journal = self.journal()
        cutoff = dt.datetime.now().replace(hour=10, minute=0, second=0, microsecond=0).timestamp()
        journal.add('WARNING', '测试错误', 'test', cutoff - 60)
        journal.flush()
        sender = AsyncMock(side_effect=[False, True])
        self.assertFalse(asyncio.run(journal.report(sender, now=cutoff + 1)))
        self.assertTrue(asyncio.run(journal.report(sender, now=cutoff + 31)))
        self.assertEqual(sender.await_count, 2)
        again = self.journal()
        self.assertFalse(asyncio.run(again.report(sender, now=cutoff + 61)))
        self.assertFalse(asyncio.run(again.report(sender, now=cutoff + 86401)))
        self.assertEqual(sender.await_count, 2)

    def test_demo_no_send_and_summary_top_ten(self):
        journal = self.journal()
        cutoff = dt.datetime.now().replace(hour=10, minute=0, second=0, microsecond=0).timestamp()
        for i in range(12):
            journal.add('ERROR', str(i) + '😀' * 300, 'worker', cutoff - 60)
        sender = AsyncMock(return_value=True)
        self.assertFalse(asyncio.run(journal.report(sender, now=cutoff + 1, demo=True)))
        sender.assert_not_awaited()
        summary = journal.summary(cutoff)
        self.assertLessEqual(len(summary.encode('utf-16-le')), 3800)
        self.assertLessEqual(summary.count('最近'), 10)

    def test_log_handler_and_async_unhandled_exception(self):
        journal = self.journal()
        async def check():
            loop = asyncio.get_running_loop()
            restore = journal.install(loop)
            try:
                logging.getLogger('test-journal').warning('测试警告 token=SECRET')
                loop.call_exception_handler({'message': '任务失败', 'exception': ValueError('token=SECRET')})
                async def bad():
                    raise RuntimeError('后台测试异常')
                task = asyncio.create_task(bad(), name='测试任务')
                task.add_done_callback(journal.task_done)
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                self.assertTrue(any('后台测试异常' in r['message'] for r in journal.rows))
            finally:
                restore()
        asyncio.run(check())
        self.assertEqual(len(journal.rows), 3)
        self.assertNotIn('SECRET', str(journal.rows))

    def test_client_disconnect_is_not_an_error(self):
        # 网页那头自己断开连接不是后台出错，不能进错误记录和日报
        journal = self.journal()
        try:
            raise ConnectionResetError(10054, '远程主机强迫关闭了一个现有的连接')
        except ConnectionResetError:
            record = logging.LogRecord('asyncio', logging.ERROR, __file__, 1, 'Exception in callback', (), __import__('sys').exc_info())
        journal.emit(record)
        self.assertFalse(journal.rows)
        journal.emit(logging.LogRecord('xiaowu', logging.ERROR, __file__, 1, '真的出错了', (), None))
        self.assertEqual(len(journal.rows), 1)
