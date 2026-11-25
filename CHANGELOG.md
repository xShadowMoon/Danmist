# 更新日志 · Changelog

每个版本的 Release 说明从这里摘出来。下载见 [Releases](https://github.com/xShadowMoon/Danmist/releases)。
Release notes for each version are taken from this file. Downloads are on the [Releases](https://github.com/xShadowMoon/Danmist/releases) page.

---

## v0.9.6 · 2026-11-25

### 安装包 · Installer

- 新增 `Danmist-Setup-v0.9.6.exe`：双击就装好（不用管理员），开始菜单和桌面都有「雾幕」，第一次打开弹框问直播间号；以后在软件里点「下载更新」；在「设置 → 应用」里能卸载，卸载时会问要不要连存档一起删。原来的免安装 zip 照旧提供。
  New `Danmist-Setup-v0.9.6.exe`: double-click to install (no admin rights), with Start menu and desktop shortcuts; the first launch asks for your room id; updates are one click inside the app; uninstall from Settings → Apps (it asks whether to delete your archives too). The portable zip is still available.
- 仓库改名为 [xShadowMoon/Danmist](https://github.com/xShadowMoon/Danmist)，旧地址会自动跳过来。
  The repository is now [xShadowMoon/Danmist](https://github.com/xShadowMoon/Danmist); old links redirect.

### OBS 弹幕 · OBS overlay

- 所有样式都能选**整体靠左 / 居中 / 靠右**（设置页「样式 → 常用 → 靠哪边」）。把 OBS 源放在画面边上时，居中的礼物卡不会再被切掉。原来的「靠右」自动换成这个。
  Every style can now be aligned **left / center / right** as a whole, so centred gift cards aren't cut off when the source sits at the edge of the canvas. The old "align right" option is migrated.
- **礼物卡大小**可以单独调（60%–150%，弹幕字号不变）；「礼物只占一行」时太长的会换行，不再超出 OBS 源。
  Gift / SC / guard cards have their own **size** slider (60–150%), and one-line gifts wrap instead of overflowing the source.
- 气泡、票根这种浅色底的样式：改过描边以后，深色字以前也描黑边，糊成一团；现在浅色卡片里的字描白边。票根样式里提督、总督的正文以前是浅色字配浅色底，现在改成深色。
  Bubble and ticket styles: dark text on light cards no longer gets a black outline once you change the outline settings (it gets a light one), and admiral / governor text in the ticket style is no longer pale on pale.
- 这个源在 OBS 里被隐藏（关掉小眼睛、切到没有它的场景）时不再画新弹幕，显示出来时一次补上，更省电脑。名字太长用省略号，不再挤成好几行。
  While the source is hidden in OBS it stops drawing and catches up when shown again, saving CPU. Very long names are truncated with an ellipsis.

### 怎么更新 · How to update

已经是 v0.9.5：顶栏点「下载更新」→「重启生效」。更早的版本：下载下面的安装包直接装，或者下载 zip 解压覆盖。
On v0.9.5: click **download update** → **restart** in the top bar. Older versions: run the installer below, or extract the zip over your folder.

---

## v0.9.5 · 2026-11-25

### 改名「雾幕 Danmist」· Renamed to Danmist

- 弹幕姬正式改名「雾幕」（英文 Danmist），换了新图标。功能、设置、存档都不变。
  The app is now called 雾幕 (Danmist) with a new icon. Features, settings and archives are unchanged.

### 桌面版 · Desktop app

- 打开方式二选一：**软件窗口**（单独一个窗口，没有黑色窗口，桌面上有「雾幕」图标；关掉窗口就停）或者**浏览器**（跟以前一样）。第一次双击 `start.bat` 时会问，以后在「设置 → 更多 → 桌面版」里改，也能在那里补建桌面快捷方式。软件窗口用的是 Windows 自带的 Edge（没有就用 Chrome），不用另外装东西。
  Choose how it opens: an **app window** (its own window, no console, a 雾幕 shortcut on the desktop; closing it stops the board) or the **browser** as before. `start.bat` asks the first time; change it later under Settings → More → Desktop, where you can also recreate the desktop shortcut. The app window uses the Edge (or Chrome) already on Windows.
- 软件内更新：有新版本时顶栏出现「下载更新」，下载并核对校验码后变成「重启生效」，点了几秒后换成新版本，窗口不用关。`config.json`、`data\`、`python\` 不会被动。只有在运行雾幕的这台电脑上能点。
  In-app updates: a **download update** button appears when a new version is out; after the download is verified it becomes **restart**, and a few seconds later you're on the new version without closing the window. `config.json`, `data\` and `python\` are left alone. Only available on the computer running the board.
- 关掉软件窗口时会先把这一场存好再退出。
  Closing the app window saves the current session before quitting.

### 修复 · Fixes

- 点歌放歌的网易云扫码：二维码带上新版 App 要的参数；扫完以后被拒绝时，以前一直停在「等扫码」看起来没反应，现在会显示原因并可以换一张。QQ 音乐扫码同样显示原因。
  Song-request QR login: the NetEase code now carries the parameter newer apps expect, and a rejected login shows the reason (with a new-code button) instead of waiting forever. QQ Music login failures show their reason too.

### 怎么更新 · How to update

这一版还要手动更新一次：关掉雾幕 → 下载下面的 zip → 解压覆盖到原来的文件夹、全部替换 → 双击 `start.bat`。以后的版本就能在软件里直接更新了。
Update by hand one last time: close the board, download the zip below, extract it over your existing folder (replace all) and run `start.bat`. From then on you can update inside the app.

---

## v0.9.4 · 2026-11-25

### 修复 · Fixes

- 扫码登录后观众名字还是打码：以前左下角的扫码登录只用来发弹幕，连直播间要另外放 `data/bili-login.json`。现在还没有连直播间的登录（或者它失效了）时，扫码登录的号会顺便用来连直播间并马上重连，新弹幕就是完整名字。
  Viewer names stayed masked after QR login: the QR login used to be for sending danmaku only. Now, if the room connection has no working login, the QR-logged-in account is also used for it and the connection is re-established, so new danmaku show full names.
- 下播期间的礼物、上舰：以前每开一场都把之前所有下播收到的带过来，感谢过的也一直挂着。现在只带没感谢的，带过来的点了感谢就不再列（「下播期间」页里照样查得到）。
  Gifts and guards received while offline were carried into every new session, even after being thanked. Now only unthanked ones carry over, and they disappear from the gift panel once thanked (still listed on the offline page).

### 新功能（试用）· New (preview)

- 弹幕点歌直接放：设置 → 点歌 → 「弹幕点歌直接放」。观众发「点歌 歌名」，从网易云或 QQ 音乐找到直接放；可以设谁能点（所有人 / 舰长以上、粉丝牌、荣耀等级、要关注）、每人同时排几首、要不要你同意、谁能发「切歌」。放法二选一：OBS 加 `/obs-music` 浏览器源（或者在页面上点喇叭出声），或者叫这台电脑上的网易云客户端放。歌单最上面显示正在放和排着的，标出是谁点的。网易云 / QQ 音乐扫码登录后会员歌也能放，登录信息只存在本机。
  Song requests that play: Settings → Song requests. Viewers send 「点歌 song name」 and it plays from NetEase Cloud Music or QQ Music, with rules for who may request, how many each, approval, and who may skip. Play it through an `/obs-music` OBS browser source (or on the page), or through the NetEase desktop client. The queue sits at the top of the song list with each requester's name. Log in by QR code for VIP songs; login data stays on your computer.

### 怎么更新 · How to update

关掉弹幕姬 → 下载下面的 zip → 解压覆盖到原来的文件夹、全部替换 → 双击 `start.bat`。`config.json` 和 `data\` 不在压缩包里，设置和存档都会保留。
Close the board, download the zip below, extract it over your existing folder (replace all) and run `start.bat`. `config.json` and `data\` are not in the zip, so your settings and archives are kept.

---

## v0.9.3 · 2026-11-25

### 新功能 · New

- 手机打开：「设置 → 链接 → 同一个 Wi-Fi 能打开」，同一个 Wi-Fi 的手机输入电脑的局域网地址就能看；新建管理链接时给二维码，手机扫一下就有管理身份。也可以在 `config.json` 写 `"lan": true`。
  Open on a phone: Settings → Links → "Open on the same Wi-Fi" lets phones on the same Wi-Fi open the board at the computer's LAN address; new admin links come with a QR code. Or set `"lan": true` in `config.json`.
- 舰长 / 提督 / 总督没放自己的图时，主页面和 OBS 用 B 站官方头像框和徽章（运行时从 B 站拿，不放进仓库）。
  Guards get Bilibili's official avatar frames and badges when you haven't added your own artwork (fetched from Bilibili at runtime, not stored in the repo).
- OBS 弹幕：刷屏时同一帧来的几条一起画、只排一次版；一秒超过 6 条不放进场动画，更省电脑。
  OBS overlay: messages arriving in the same frame are drawn together with one layout pass, and entrance animations pause when more than 6 arrive per second.
- OBS 场景名里写 `[雾凇]`（或 `[rime]`）之类，切到这个场景弹幕自动换成这个样式，切回没写的场景换回原样（浏览器源要给「读取用户信息」权限）。
  Put a style tag such as `[rime]` in an OBS scene name and the overlay switches to that style in that scene (the browser source needs the "read user information" permission).
- 上舰、弹幕、礼物没带头像的人，后台去 B 站名片接口查到后自动补上（不带登录，一秒多一个）。
  Viewers without an avatar (for example in guard purchases) get one filled in from Bilibili's public user card, about one lookup per second.
- 顶栏按钮可以自己选：主页面在「设置 → 外观 → 顶栏按钮」，OBS 设置页点右上角的眼睛。
  Choose which top-bar buttons show: Settings → Appearance → Top bar on the dashboard, and the eye button on the OBS setup page.

### 修复和调整 · Fixes and changes

- 荣耀等级：服务刚启动那几秒打开的页面拿不到官方图标，以前会一直显示色块；现在会再问几次，拿到就换成官方图。图标也存一份在 `data/`，重启后马上就有。OBS 设置页的预览示例也带上了荣耀等级。
  Honor level badges no longer stay as plain colour blocks when a page was opened right after startup; icons are retried, cached in `data/`, and shown in the OBS preview samples.
- 去掉了从别的版本带过来的专属样式（OBS 弹幕的薄雾、留言本，歌单的薄雾、留言本，以及 Q 版主播、探头主播、标题字），旧网址自动换成月见 / 卡片；示例里的粉丝牌改叫「粉丝团」。
  Removed the streamer-specific styles carried over from another build (mist and diary for danmaku and songs, mascot options); old URLs fall back to moon / card. The sample fan medal is now called "粉丝团".
- 窄屏时弹幕栏的直播间按钮不再压住「全部」筛选。
  The room switcher no longer overlaps the danmaku filter on narrow windows.
- 扫码登录处和 README 加了免责声明：用账号登录、发弹幕等操作有被 B 站限制或封禁的风险，由使用者自己承担。
  Added a disclaimer next to QR login and in the README: using your account through a third-party tool may get it restricted or banned by Bilibili, at your own risk.

### 怎么更新 · How to update

关掉弹幕姬 → 下载下面的 zip → 解压覆盖到原来的文件夹、全部替换 → 双击 `start.bat`。`config.json` 和 `data\` 不在压缩包里，设置和存档都会保留。
Close the board, download the zip below, extract it over your existing folder (replace all) and run `start.bat`. `config.json` and `data\` are not in the zip, so your settings and archives are kept.

---

## v0.9.2 · 2026-11-24

### 朗读可以用 AI 音色（GPT-SoVITS）· AI voices for text-to-speech

- 可选：在 `config.json` 里接上本机的 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)（官方 `api_v2.py`），「设置 → 朗读 → 声音」里就会多出「AI 音色」，可以用自己训练的声音朗读。怎么训练、怎么写配置见 README 的「AI 音色」。
  Optional: connect a local GPT-SoVITS server (the official `api_v2.py`) in `config.json` and "AI voices" appear under Settings → Text-to-speech → Voice, so you can read aloud in a voice you trained. See "AI voices" in the README for training and setup.
- 默认 AI 声音只念礼物、上舰、关注、进房的感谢；弹幕和 SC 是观众写的字，照常用浏览器的声音。想全部用 AI 声音，把「AI 声音念」改成「全部」。
  By default the AI voice only reads the thank-you lines for gifts, guards, follows and entries; danmaku and SC (written by viewers) keep the browser voice. Switch "AI voice reads" to "everything" to change that.
- 只有管理身份能用。正在念的时候后面两句先合成好；AI 声音没开或者 10 秒还没合成好，这一句就改用浏览器的声音。
  Admins only. The next two lines are prepared while one plays; if the AI server is off or a line takes more than 10 seconds, that line falls back to the browser voice.
- 弹幕姬本身不带模型和 PyTorch，不接 GPT-SoVITS 就和以前完全一样。
  No models or PyTorch are bundled; without GPT-SoVITS nothing changes.

### 怎么更新 · How to update

关掉弹幕姬 → 下载下面的 zip → 解压覆盖到原来的文件夹、全部替换 → 双击 `start.bat`。`config.json` 和 `data\` 不在压缩包里，设置和存档都会保留。
Close the board, download the zip below, extract it over your existing folder (replace all) and run `start.bat`. `config.json` and `data\` are not in the zip, so your settings and archives are kept.

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
