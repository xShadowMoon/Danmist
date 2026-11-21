<a id="zh"></a>

# bili-danmaku-board 弹幕姬

**中文** | [English](#english)

B 站直播用的弹幕工作台。在自己电脑上运行，连上一个直播间，在网页里看弹幕、礼物、SC 和上舰，还能给 OBS 提供弹幕和歌单的浏览器源。每一场直播都会自动存档，之后可以回看。

## 功能

- **弹幕栏**：表情显示成图片，粉丝牌、荣耀等级、高亮词，全场搜索，查看某个观众的历史弹幕，回复某条弹幕，用自己的账号发弹幕，禁言。
- **礼物 / SC / 上舰**：礼物记录和送礼榜（本场、本周、本月），大礼物特效，上舰特效（开通 / 续费 / 陪伴第 N 天），SC 置顶，已读状态在多台设备间同步。
- **观众**：备注、跨场档案、舰长列表和到期时间、在线观众、进房和关注。
- **歌单**：歌曲库、弹幕点歌、「正在唱」、歌词弹窗，OBS 歌单有五种样式。
- **朗读**：用浏览器自带的声音朗读弹幕、SC 和礼物，可以设过滤条件。
- **历史**：每场完整保存弹幕、礼物、SC 和上舰；下播期间收到的另外列出来。
- **OBS 显示**：`/obs`（弹幕、礼物、SC、上舰，8 种样式）和 `/obs-songs`，在 `/obs-setup` 里可视化设置。
- **布局**：模块可以拖动和调大小，主题、配色、深色模式、紧凑模式，预设可以导出导入；可以装成桌面应用（PWA）。
- **分享**：公开只读链接、可以随时新建和作废的管理链接，还有给主播本人用的链接（`/host`）。
- **切换直播间**：可以临时看你列出来的其他直播间，不影响自己的记录。
- 可选：和 B 站的连接或者你的公网地址断了，发 Discord 提醒。

## 需要

- Python 3.11 或更新
- `pip install -r requirements.txt`
- 弹幕连接用的是 xfgryujk 的 [blivedm](https://github.com/xfgryujk/blivedm)（MIT），放在 `blivedm-src/` 里，有少量改动。

## 快速开始

```sh
pip install -r requirements.txt
cp config.example.json config.json   # 把 room 改成你的直播间号
python server.py                     # Windows 也可以双击 start.bat
```

打开 <http://127.0.0.1:8373>。在本机打开的页面拥有全部管理权限。

没有直播间也能先看看：`python server.py --demo --port 8375`（或者双击 `demo.bat`）会生成假弹幕，可以把每种样式都看一遍。

## 配置

`config.json`（除了 `room` 都可以不填；命令行参数会覆盖它，见 `python server.py --help`）：

| 键 | 含义 |
| --- | --- |
| `room` | 要连接的直播间号。 |
| `anchor_name` | 你的名字，显示在切换直播间的列表里。 |
| `port`、`host` | 网页监听的地址，默认 `127.0.0.1:8373`。 |
| `login_file` | 一个 B 站账号的登录文件，格式 `{"cookie": "SESSDATA=...; bili_jct=...; DedeUserID=..."}`，用来读取直播间。不登录的话 B 站会把观众名字打码。默认 `data/bili-login.json`。 |
| `public_url` | 如果你把页面放到了公网，填公网地址（用于「隧道断了」提醒）。 |
| `discord_webhook` | 连接提醒发到的 Discord webhook。留空就不提醒。 |
| `bot_say_url` | 可选：用机器人账号发弹幕的本地接口（POST `{"text": ...}`，请求头 `X-Local-Token` 读自 `bot.token`）。 |

其他本地文件（都不会进 git）：

- `admin.key`：里面写一串随机字符就能开启管理链接（`/?admin=<那串字符>`）。也可以在页面里新建可作废的管理链接。
- `data/`：直播存档、设置、观众备注和登录的账号。记得备份，千万别公开。

### 放到公网

默认只监听 `127.0.0.1`。想分享给房管或主播，就放在反向代理或隧道（比如 Cloudflare Tunnel）后面，并填好 `public_url`。没有管理链接的人只能看只读页面，看不到收益和历史。

### 自己的图片

除了应用图标，不带任何美术图。舰长徽章、头像框、横幅和看板娘用到的文件名见 [`static/art/README.md`](static/art/README.md)。

## 测试

```sh
python tests/run_tests.py     # 离线后端测试
python tests/smoke_demo.py    # 在 8390 端口启动演示服务器，检查页面和 WebSocket
```

## 字体

`static/fonts/` 里可选的 OBS 字体是 SIL Open Font License 1.1 字体的子集，来源见 [`static/fonts/LICENSES.txt`](static/fonts/LICENSES.txt)。

## 许可

[MIT](LICENSE)。`blivedm-src/` 保留它自己的 MIT 许可。

本项目与哔哩哔哩无关，请遵守 B 站的用户协议。

---

<a id="english"></a>

# English

[中文](#zh) | **English**

A self-hosted live-stream dashboard for **Bilibili Live** streamers. It connects to one live room, shows danmaku, gifts, Super Chats and guard purchases in a customizable web page, and serves OBS browser sources for on-stream overlays. Every stream is archived so you can look back at past sessions.

## Features

- **Danmaku panel**: live danmaku with emoticons as images, fan medals, honour levels, highlight words, search through the whole stream, per-viewer history, reply to a message, send danmaku with your own account, mute viewers.
- **Gifts / SC / guards**: gift log and ranking (this stream, week, month), big gift effects, guard purchase effects with "new / renew / day N", SC pinning with read state synced across devices.
- **Viewers**: notes, profiles across streams, guard list with expiry, who is online, entries and follows.
- **Song list**: song library, requests from danmaku, "now singing", lyrics pop-out, OBS song list with five styles.
- **Text-to-speech** for danmaku, SC and gifts using the browser's voices, with filters.
- **History**: every stream is archived with its full danmaku, gifts, SC and guards; things received while offline are listed separately.
- **OBS overlays**: `/obs` (danmaku, gifts, SC, guards; 8 styles) and `/obs-songs`, configured visually at `/obs-setup`.
- **Layout**: drag and resize panels, themes, colour palettes, dark mode, compact mode, presets that can be exported and imported; installable as a desktop app (PWA).
- **Sharing**: a public read-only link, admin links you can create and revoke, and a separate host link (`/host`) for the streamer.
- **Room switching**: viewers of the page can peek at other live rooms from a list you control, without touching your own records.
- Optional Discord alerts when the connection to Bilibili or your public URL goes down.

## Requirements

- Python 3.11 or newer
- `pip install -r requirements.txt`
- Danmaku connection uses [blivedm](https://github.com/xfgryujk/blivedm) by xfgryujk (MIT), bundled in `blivedm-src/` with small local changes.

## Quick start

```sh
pip install -r requirements.txt
cp config.example.json config.json   # then set room to your live room id
python server.py                     # on Windows you can also double-click start.bat
```

Open <http://127.0.0.1:8373>. Pages opened on the same computer have full admin rights.

Try it without a live room: `python server.py --demo --port 8375` (or `demo.bat`) generates fake danmaku so you can look at every style.

## Configuration

`config.json` (all optional except `room`; command-line flags override it, see `python server.py --help`):

| Key | Meaning |
| --- | --- |
| `room` | Live room id to connect to. |
| `anchor_name` | Your name, shown in the room switcher. |
| `port`, `host` | Where the web page listens. Default `127.0.0.1:8373`. |
| `login_file` | JSON file `{"cookie": "SESSDATA=...; bili_jct=...; DedeUserID=..."}` of a Bilibili account used to read the room. Without it Bilibili masks viewer names. Default `data/bili-login.json`. |
| `public_url` | Your public address if you expose the page (for the "tunnel is down" alert). |
| `discord_webhook` | Discord webhook for connection alerts. Empty = no alerts. |
| `bot_say_url` | Optional local endpoint that sends danmaku from a bot account (POST `{"text": ...}`, header `X-Local-Token` read from `bot.token`). |

Other local files (all ignored by git):

- `admin.key`: put a random string in it to enable admin links (`/?admin=<string>`). You can also create revocable admin links from the page.
- `data/`: stream archives, settings, viewer notes and logged-in accounts. Back it up; never publish it.

### Exposing the page

By default it only listens on `127.0.0.1`. To share it with moderators or the streamer, put it behind a reverse proxy or tunnel (for example Cloudflare Tunnel) and set `public_url`. Visitors without an admin link get a read-only view without revenue or history.

### Your own artwork

No artwork is included apart from the app icon. See [`static/art/README.md`](static/art/README.md) for the file names used for guard badges, avatar frames, banners and mascots.

## Tests

```sh
python tests/run_tests.py     # offline backend tests
python tests/smoke_demo.py    # starts a demo server on port 8390 and checks the pages and WebSocket
```

## Fonts

The optional OBS fonts in `static/fonts/` are subsets of fonts under the SIL Open Font License 1.1. Sources are listed in [`static/fonts/LICENSES.txt`](static/fonts/LICENSES.txt).

## License

[MIT](LICENSE). `blivedm-src/` keeps its own MIT license.

This project is not affiliated with Bilibili. Use it in line with Bilibili's terms of service.
