"""第六轮共用替身：没有预设返回的网络请求立即失败，不读取真实账号。"""
import copy
import os
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import server
from test_backend import TemporaryDataTest, run_without_io


class Reply:
    def __init__(self, payload=None, status=200, error=None):
        self.payload, self.status, self.error = payload, status, error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self, **kwargs):
        return copy.deepcopy(self.payload)


class Http:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.cookie_jar = SimpleNamespace(update_cookies=Mock())

    def request(self, method, url, **kwargs):
        # 表单会在重试时原地修改，保存副本才能发现第一次是否真的带了回复字段。
        self.calls.append((method, url, copy.deepcopy(kwargs)))
        if not self.replies:
            raise AssertionError('未预设的网络请求：' + url)
        return self.replies.pop(0)

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)

    async def close(self):
        pass


class Ws:
    def __init__(self, commands=()):
        self.messages = iter(commands)
        self.sent, self.closed = [], False

    async def prepare(self, request):
        pass

    async def send_json(self, value):
        self.sent.append(copy.deepcopy(value))

    async def send_str(self, value):
        self.sent.append(json.loads(value))

    async def close(self, **kwargs):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            command = next(self.messages)
        except StopIteration:
            raise StopAsyncIteration
        return SimpleNamespace(type=server.aiohttp.WSMsgType.TEXT, data=json.dumps(command))


def request(query=None, admin=True):
    return SimpleNamespace(query=query or {}, cookies={}, match_info={},
                           headers={'Origin': 'http://127.0.0.1:8390'} if admin else {'CF-Connecting-IP': '192.0.2.1'},
                           remote='127.0.0.1', host='127.0.0.1:8390' if admin else 'example.invalid')


def discard_task(coro):
    # 后台轮询在本测试里不能运行，相关函数另有直接调用的测试。
    coro.close()
    return Mock()


class RoundSixTest(TemporaryDataTest):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(server, 'load_cookie', side_effect=AssertionError('禁止读取真实登录')))
        self.enterContext(patch.object(server.aiohttp, 'ClientSession', side_effect=AssertionError('禁止真实网络')))
        self.state = server.MemState(123)
        self.hub = server.Hub(self.state, server.NullHistory(), persist=False)
        self.hub.emit = Mock()
        self.hub.emit_admin = Mock()

    def bootstrap(self, demo=True):
        """运行真正的 main 注册路由，在监听端口前停止；不靠提取源码或读取闭包测试。"""
        class Ready(Exception):
            pass

        captured = {}
        real_hub = server.Hub
        self.bare, self.session = Http(), Http()

        def hub_factory(*args, **kwargs):
            captured['hub'] = real_hub(*args, **kwargs)
            captured['hub'].emit = Mock()
            captured['hub'].emit_admin = Mock()
            return captured['hub']

        def runner_factory(app, **kwargs):
            captured['app'] = app
            return SimpleNamespace(setup=AsyncMock(side_effect=Ready))

        # 2026-11-26 合并后：不读电脑上的 config.json；正式模式要给房间号和代发弹幕的接口（以前写死在代码里）
        argv = ['server.py', '--config', os.path.join(self.root, 'no-config.json'), '--port', '8390'] + (['--demo'] if demo else ['--room', '1000001', '--bot-say-url', 'http://127.0.0.1:18771/api/danmu/say'])
        with patch.object(server.sys, 'argv', argv), \
                patch.object(server.aiohttp, 'ClientSession', side_effect=[self.bare, self.session]), \
                patch.object(server, 'Hub', side_effect=hub_factory), \
                patch.object(server, 'clean_img_cache'), \
                patch.object(server, 'load_cookie', return_value=''), \
                patch.object(server, 'page_vers', return_value={}), \
                patch.object(server.logging, 'basicConfig'), \
                patch.object(server.ErrorJournal, 'install', return_value=lambda: None), \
                patch.object(server.asyncio, 'get_running_loop', return_value=Mock()), \
                patch.object(server.web.UrlDispatcher, 'add_static'), \
                patch.object(server.web, 'AppRunner', side_effect=runner_factory):
            with self.assertRaises(Ready):
                run_without_io(server.main())
        self.hub = captured['hub']
        self.state = self.hub.state
        self.routes = {r.resource.canonical: r.handler for r in captured['app'].router.routes()}

    def websocket(self, commands, query=None):
        ws = Ws(commands)
        with patch.object(server.web, 'WebSocketResponse', return_value=ws), \
                patch.object(server, 'page_vers', return_value={}), \
                patch.object(server.asyncio, 'create_task', side_effect=discard_task):
            run_without_io(self.routes['/ws'](request(query)))
        return ws
