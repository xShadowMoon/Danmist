# 更新日志 · Changelog

每个版本的 Release 说明从这里摘出来。下载见 [Releases](https://github.com/xShadowMoon/bili-danmaku-board/releases)。
Release notes for each version are taken from this file. Downloads are on the [Releases](https://github.com/xShadowMoon/bili-danmaku-board/releases) page.

---

## v0.9.1 · 2026-11-23

### 修复 · Fix

- 「历史」里点某一场打不开详情（页面报错，一直停在列表）。这个问题 0.9.0 里就有，现在点进去能看到概览、送礼榜、SC、礼物、上舰和整场弹幕。
  Clicking a stream in History did nothing (a script error kept it on the list). This was broken in 0.9.0; the detail view with summary, rankings, SC, gifts, guards and full danmaku works again.

### 有新版本时提醒 · Update reminder

- GitHub 上出了新版本时，顶栏「已连接」旁边会出现「有新版本 vX.Y.Z · 看看」，点开就是更新内容和下载页；点 ✕ 这个版本就不再提示。
  When a new version is on GitHub, a "new version vX.Y.Z" tag appears next to the connection status at the top; it links to the release notes and download. Click ✕ to hide it for that version.
- 只有管理身份能看到（普通链接、主播专属链接、OBS 都不显示）。程序不会自己下载或更新任何东西。
  Only admins see it (not the public link, host link or OBS). The app never downloads or updates anything by itself.
- 启动后查一次，之后每天一次，只读 GitHub 上最新 Release 的版本号。不想检查：`config.json` 写 `"update_check": false`，或者加 `--no-update-check`。
  Checked at startup and then once a day, reading only the latest release's version number. Turn it off with `"update_check": false` in `config.json` or `--no-update-check`.
- 新增 `python server.py --version` 查看当前版本。
  New `python server.py --version`.
- README 加了「更新到新版本」的步骤。
  The README now has update steps.

### 怎么更新 · How to update

**从 0.9.0 升级这一次要手动来**（0.9.0 还没有提醒功能）：关掉弹幕姬 → 下载下面的 zip → 解压覆盖到原来的文件夹、全部替换 → 双击 `start.bat`。`config.json` 和 `data\` 不在压缩包里，设置和存档都会保留。

**Updating from 0.9.0 is manual this once** (0.9.0 has no reminder): close the app → download the zip below → unzip over your existing folder, replacing files → run `start.bat`. `config.json` and `data\` are not in the zip, so settings and archives are kept.

---

## v0.9.0 · 2026-11-23

第一个公开发布的版本。弹幕姬原本是给一位主播自用的工具，开源前已经在直播间里用了两周、更新过 62 次（分在 9 个更新日），所以版本号从 0.9 开始；等更多人用过、稳定下来再出 1.0。这一版整理成通用版本公开：直播间号、主播名字、登录文件、掉线提醒都改成在 `config.json` 里设置，去掉了所有专属美术和链接。

First public release. The dashboard started as a tool for one streamer and had already been used live for two weeks, with 62 updates over 9 release days, hence 0.9 rather than 1.0; 1.0 will come once more people have used it. This version is the general-purpose edition, with room id, streamer name, login file and alerts all set in `config.json`, and no bundled artwork or private links.

### 下载 · Download

- **Windows（推荐）**：`bili-danmaku-board-v0.9.0-windows-x64.zip`，自带 Python 3.13，解压后双击 `start.bat`。
  Windows (recommended): Python 3.13 bundled; unzip and double-click `start.bat`.
- **源码 · Source**：页面下方的 Source code，需要 Python 3.11 以上，见 README「从源码运行」。
  Source code: needs Python 3.11+, see "Running from source" in the README.

### 主要功能 · Highlights

- 弹幕、SC、礼物、上舰、点歌、观众、进房都在一个可以自由拖动的网页里；深浅色、配色、紧凑模式，可装成桌面应用。
  Danmaku, Super Chats, gifts, guards, song requests, viewers and entries in one drag-and-drop page; light/dark, palettes, compact mode, installable as a PWA.
- OBS 弹幕 8 种样式、OBS 歌单 5 种样式，在 `/obs-setup` 可视化设置，实时预览。
  8 OBS danmaku styles and 5 song-list styles, configured visually at `/obs-setup` with a live preview.
- 礼物播 B 站官方动图，大礼物和上舰优先用官方特效；送礼榜本场 / 本周 / 本月。
  Official animated gift icons and big gift / guard effects; gift ranking for this stream, week and month.
- 每场自动存档，历史里看收益、送礼榜和整场弹幕；下播期间收到的礼物单独列出。
  Every stream archived with revenue, rankings and full danmaku; gifts received while offline are listed separately.
- 扫码登录自己的号发弹幕、回复弹幕、改标题分区；朗读和分事件提示音。
  QR login to send and reply to danmaku and change the title/area; text-to-speech and per-event sounds.
- 只读普通链接、可作废的管理链接、主播专属链接；可以临时切去看别的直播间。
  Read-only public link, revocable admin links and a host link; peek at other live rooms.

### 这一版的改动 · Changes in this version

- 新增 Windows 免安装包（自带 Python），以及打包脚本 `scripts/build-windows.ps1`。
  New portable Windows package with bundled Python, built by `scripts/build-windows.ps1`.
- `start.bat` 第一次运行会问直播间号并写进 `config.json`；从源码运行时自动找 Python、自动装依赖。
  `start.bat` asks for the room id on first run and writes `config.json`; when run from source it finds Python and installs dependencies automatically.
- 修复：`requirements.txt` 漏了 `qrcode`，导致页面里扫码登录失败。
  Fix: `requirements.txt` was missing `qrcode`, so QR login in the page failed.
- README 重写：下载使用步骤、接 OBS、功能表、截图、常见问题、数据与隐私。
  README rewritten with setup steps, OBS guide, feature table, screenshots, FAQ and privacy notes.

### 已知问题 · Known issues

- `tests/test_retention.py` 里有两个测试和日期有关，目前会失败，不影响使用。
  Two date-dependent tests in `tests/test_retention.py` currently fail; this doesn't affect the app.
- 「改直播间公告」B 站接口返回成功，但公告可能要过审核才会变。
  Bilibili accepts room-notice changes, but the new notice may only show after review.

### 第三方组件 · Third-party components

- [blivedm](https://github.com/xfgryujk/blivedm)（MIT），在 `blivedm-src/`。
- OBS 字体为 SIL Open Font License 1.1 字体的子集，见 `static/fonts/LICENSES.txt`。
  OBS fonts are OFL 1.1 subsets, see `static/fonts/LICENSES.txt`.
- Windows 包内含 [Python](https://www.python.org/)（PSF License）和 aiohttp、Brotli、pure-protobuf、yarl、qrcode 等依赖，各自保留原许可。
  The Windows package includes Python (PSF License) and its dependencies (aiohttp, Brotli, pure-protobuf, yarl, qrcode, …) under their own licenses.

---

## 2026-11-21 · 开源 · Open-sourced

仓库公开（没有打版本号）。Repository made public (untagged).
