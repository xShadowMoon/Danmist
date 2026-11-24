"""AI 音色（ai_voice.py）：用假的说话服务测两种接口、缓存、排队上限。"""
import asyncio
import os
import sys
import unittest

import aiohttp
from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_voice  # noqa: E402
from ai_voice import AIVoice, Busy, VoiceError  # noqa: E402

WAV = b'RIFF' + b'\0' * 40


async def fake_server(api):
    calls = []

    async def voices(request):
        return web.json_response({'voices': ['roxy', 'alice', 'secret']})

    async def folder_tts(request):
        calls.append(('tts', request.query.get('voice'), (await request.read()).decode(), request.query.get('speed')))
        if request.query.get('voice') == 'bad':
            return web.json_response({'error': '没有这个音色: bad'}, status=400)
        await asyncio.sleep(0.05)
        return web.Response(body=WAV, content_type='audio/wav')

    async def v2_tts(request):
        j = await request.json()
        calls.append(('tts', j))
        return web.Response(body=WAV, content_type='audio/wav')

    async def setw(request):
        calls.append((request.path, request.query.get('weights_path')))
        return web.json_response({'message': 'success'})

    app = web.Application()
    if api == 'folder':
        app.router.add_get('/voices', voices)
        app.router.add_post('/tts', folder_tts)
    else:
        app.router.add_post('/tts', v2_tts)
        app.router.add_get('/set_gpt_weights', setw)
        app.router.add_get('/set_sovits_weights', setw)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f'http://127.0.0.1:{port}', calls


class AIVoiceTests(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.run(coro)

    def test_disabled(self):
        async def go():
            async with aiohttp.ClientSession() as s:
                v = AIVoice({})
                self.assertFalse(v.enabled)
                self.assertEqual(await v.voices(s), ([], False))
        self.run_async(go())

    def test_folder_list_speak_cache(self):
        async def go():
            runner, url, calls = await fake_server('folder')
            try:
                async with aiohttp.ClientSession() as s:
                    v = AIVoice({'url': url, 'names': {'alice': '爱丽丝'}, 'hide': ['secret']})
                    rows, online = await v.voices(s)
                    self.assertTrue(online)
                    self.assertEqual(rows, [{'id': 'alice', 'name': '爱丽丝'}, {'id': 'roxy', 'name': 'roxy'}])
                    self.assertEqual(await v.speak(s, 'alice', '谢谢舰长', 3), WAV)
                    self.assertEqual(calls[-1], ('tts', 'alice', '谢谢舰长', '2.0'))  # 语速限制在 0.5–2
                    await v.speak(s, 'alice', '谢谢舰长', 3)
                    self.assertEqual(len(calls), 1)  # 第二次用缓存
                    with self.assertRaises(VoiceError):
                        await v.speak(s, 'bad', '你好')
                    with self.assertRaises(VoiceError):
                        await v.speak(s, 'alice', '   ')
                    await v.speak(s, 'alice', '长' * 400)
                    self.assertEqual(len(calls[-1][2]), ai_voice.MAX_CHARS)
            finally:
                await runner.cleanup()
        self.run_async(go())

    def test_busy(self):
        async def go():
            runner, url, calls = await fake_server('folder')
            try:
                async with aiohttp.ClientSession() as s:
                    v = AIVoice({'url': url})
                    res = await asyncio.gather(*(v.speak(s, 'alice', f'第{i}句') for i in range(ai_voice.MAX_WAITING + 2)),
                                               return_exceptions=True)
                    self.assertEqual(sum(isinstance(r, Busy) for r in res), 2)
                    self.assertEqual(sum(r == WAV for r in res), ai_voice.MAX_WAITING)
            finally:
                await runner.cleanup()
        self.run_async(go())

    def test_offline(self):
        async def go():
            async with aiohttp.ClientSession() as s:
                v = AIVoice({'url': 'http://127.0.0.1:1'})
                self.assertEqual(await v.voices(s), ([], False))
        self.run_async(go())

    def test_api_v2(self):
        async def go():
            runner, url, calls = await fake_server('api_v2')
            try:
                async with aiohttp.ClientSession() as s:
                    v = AIVoice({'url': url, 'api': 'api_v2', 'voices': [
                        {'name': '我的声音', 'ref_audio': 'D:/v/me.wav', 'ref_text': '你好呀', 'gpt': 'me.ckpt', 'sovits': 'me.pth', 'speed': 1.1},
                        {'id': 'b', 'name': '另一个', 'ref_audio': 'D:/v/b.wav', 'ref_text': '嗨', 'ref_lang': 'ja', 'gpt': 'b.ckpt', 'sovits': 'b.pth'},
                        {'name': '没参考音频的不算'}]})
                    rows, online = await v.voices(s)
                    self.assertTrue(online)  # 根路径 404 也算服务开着
                    self.assertEqual(rows, [{'id': '我的声音', 'name': '我的声音'}, {'id': 'b', 'name': '另一个'}])
                    await v.speak(s, '我的声音', '谢谢', 1.0)
                    self.assertEqual(calls[0], ('/set_gpt_weights', 'me.ckpt'))
                    self.assertEqual(calls[1], ('/set_sovits_weights', 'me.pth'))
                    req = calls[2][1]
                    self.assertEqual((req['text'], req['ref_audio_path'], req['prompt_text'], req['prompt_lang'], req['speed_factor']),
                                     ('谢谢', 'D:/v/me.wav', '你好呀', 'zh', 1.1))
                    await v.speak(s, '我的声音', '再来一句')
                    self.assertEqual(len(calls), 4)  # 同一个音色不再换模型
                    await v.speak(s, 'b', '你好')
                    self.assertEqual([c[0] for c in calls[4:]], ['/set_gpt_weights', '/set_sovits_weights', 'tts'])
                    self.assertEqual(calls[-1][1]['prompt_lang'], 'ja')
            finally:
                await runner.cleanup()
        self.run_async(go())


if __name__ == '__main__':
    unittest.main()
