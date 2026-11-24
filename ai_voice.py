"""AI 音色（2026-11-24）：朗读时把要念的字交给本机的 GPT-SoVITS 服务，拿回 wav 给网页播放。

两种接口（配置里的 "api"）：
  folder   一个音色一个文件夹的说话服务：GET /voices → {"voices": [...]}，POST /tts?voice=名字（请求体是文字）→ wav
  api_v2   GPT-SoVITS 自带的 api_v2.py（python api_v2.py，默认 http://127.0.0.1:9880）；
           每个音色在配置里写参考音频、参考音频的文字和训练出来的两个模型文件，切换音色时自动换模型

只有管理身份能用（server.py 里判断），不然谁都能拿这个接口让 AI 声音说任意的话。
"""
import asyncio
import collections
import logging
import time

import aiohttp

log = logging.getLogger('ai_voice')

MAX_CHARS = 150      # 一句最多送多少字过去，太长的截掉（弹幕本来就截到 40 字左右）
CACHE_ITEMS = 48     # 最近合成过的句子留着，试听、重听 SC 时不用再算一遍
MAX_WAITING = 4      # 同一时间最多排几句，再多就直接说忙（网页会改用浏览器语音）


class Busy(Exception):
    pass


class VoiceError(Exception):
    pass


def _clean_voices(rows):
    out = []
    for i, v in enumerate(rows or []):
        if not isinstance(v, dict) or not v.get('ref_audio'):
            continue
        vid = str(v.get('id') or v.get('name') or f'voice{i + 1}')
        out.append({**v, 'id': vid, 'name': str(v.get('name') or vid)})
    return out


class AIVoice:
    def __init__(self, conf=None):
        conf = conf if isinstance(conf, dict) else {}
        self.url = str(conf.get('url') or '').rstrip('/')
        self.api = 'api_v2' if conf.get('api') == 'api_v2' else 'folder'
        self.names = conf.get('names') if isinstance(conf.get('names'), dict) else {}
        self.hidden = set(conf.get('hide') or [])
        self.conf_voices = _clean_voices(conf.get('voices')) if self.api == 'api_v2' else []
        self.timeout = float(conf.get('timeout') or 60)  # 第一次要装模型，可能要半分钟以上
        self.lock = asyncio.Lock()
        self.waiting = 0
        self.cache = collections.OrderedDict()
        self.listed = (0.0, [], False)   # (什么时候查的, 音色, 服务在不在)
        self.loaded = None               # api_v2 现在装着哪一套模型

    @property
    def enabled(self):
        return bool(self.url)

    async def voices(self, session):
        """[{id, name}]，服务没开时 online=False。30 秒内重复问就用上次的结果。"""
        if not self.enabled:
            return [], False
        at, rows, online = self.listed
        if time.time() - at < (30 if online else 8):
            return rows, online
        rows, online = [], False
        try:
            if self.api == 'folder':
                async with session.get(self.url + '/voices', timeout=aiohttp.ClientTimeout(total=4)) as r:
                    j = await r.json(content_type=None)
                ids = [str(x) for x in (j.get('voices') or []) if str(x) not in self.hidden]
                order = list(self.names)  # 配置里写了名字的排前面
                ids.sort(key=lambda x: (order.index(x) if x in order else len(order), x))
                rows = [{'id': x, 'name': str(self.names.get(x) or x)} for x in ids]
            else:
                # 官方 api_v2 没有「列出音色」的接口：音色写在配置里，这里只看服务开没开（随便问一下，有回应就算开着）
                async with session.get(self.url + '/', timeout=aiohttp.ClientTimeout(total=4)) as r:
                    await r.read()
                rows = [{'id': v['id'], 'name': v['name']} for v in self.conf_voices]
            online = True
        except Exception:
            rows, online = [], False
        self.listed = (time.time(), rows, online)
        return rows, online

    async def speak(self, session, voice, text, speed=1.0):
        text = ''.join(list(str(text or '').strip())[:MAX_CHARS])
        if not text:
            raise VoiceError('没有文字')
        speed = round(min(2.0, max(0.5, float(speed or 1))), 2)
        key = (voice, text, speed)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if self.waiting >= MAX_WAITING:
            raise Busy('AI 音色忙不过来')
        self.waiting += 1
        try:
            async with self.lock:
                if key in self.cache:
                    return self.cache[key]
                if self.api == 'folder':
                    wav = await self._folder(session, voice, text, speed)
                else:
                    wav = await self._api_v2(session, voice, text, speed)
        finally:
            self.waiting -= 1
        if wav[:4] != b'RIFF':
            raise VoiceError('服务返回的不是声音')
        self.cache[key] = wav
        while len(self.cache) > CACHE_ITEMS:
            self.cache.popitem(last=False)
        return wav

    async def _folder(self, session, voice, text, speed):
        async with session.post(self.url + '/tts', params={'voice': voice, 'speed': str(speed)}, data=text.encode('utf-8'),
                                headers={'Content-Type': 'text/plain; charset=utf-8'},
                                timeout=aiohttp.ClientTimeout(total=self.timeout)) as r:
            body = await r.read()
            if r.status != 200:
                raise VoiceError(_err(body) or f'HTTP {r.status}')
            return body

    async def _api_v2(self, session, voice, text, speed):
        v = next((x for x in self.conf_voices if x['id'] == voice), None)
        if not v:
            raise VoiceError('没有这个音色')
        want = (v.get('gpt') or '', v.get('sovits') or '')
        if want != self.loaded and any(want):
            for path, ep in ((want[0], 'set_gpt_weights'), (want[1], 'set_sovits_weights')):
                if not path:
                    continue
                async with session.get(f'{self.url}/{ep}', params={'weights_path': path},
                                       timeout=aiohttp.ClientTimeout(total=120)) as r:
                    body = await r.read()
                    if r.status != 200:
                        self.loaded = None
                        raise VoiceError('换模型失败：' + (_err(body) or f'HTTP {r.status}'))
            self.loaded = want
        req = {'text': text, 'text_lang': v.get('text_lang') or 'zh', 'ref_audio_path': v['ref_audio'],
               'prompt_text': v.get('ref_text') or '', 'prompt_lang': v.get('ref_lang') or 'zh',
               'text_split_method': 'cut5', 'batch_size': 1, 'media_type': 'wav', 'streaming_mode': False,
               'speed_factor': round(speed * float(v.get('speed') or 1), 2)}
        for k in ('top_k', 'top_p', 'temperature'):
            if k in v:
                req[k] = v[k]
        async with session.post(self.url + '/tts', json=req, timeout=aiohttp.ClientTimeout(total=self.timeout)) as r:
            body = await r.read()
            if r.status != 200:
                raise VoiceError(_err(body) or f'HTTP {r.status}')
            return body


def _err(body):
    try:
        import json
        j = json.loads(body.decode('utf-8', 'replace'))
        return str(j.get('error') or j.get('message') or j.get('Exception') or '')[:200]
    except Exception:
        return body[:120].decode('utf-8', 'replace') if body else ''
