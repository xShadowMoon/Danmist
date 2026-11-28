# 更新日志 · Changelog

每个版本的 Release 说明从这里摘出来。下载见 [Releases](https://github.com/xShadowMoon/Danmist/releases)。
Release notes for each version are taken from this file. Downloads are on the [Releases](https://github.com/xShadowMoon/Danmist/releases) page.

---

## v0.9.15.5 · 2026-11-28

- 设置 → 更多 →「检查更新」点了马上去 GitHub 查。以前它只看开软件时自动查的那一次，开着软件期间发的新版本要等到第二天才看得到。
  "Check for updates" now asks GitHub right away. It used to only show the result of the automatic check made at startup, so a release made while the app was open showed up a day later.

---

## v0.9.15.4 · 2026-11-28

- 没登录（游客）时 B 站会把弹幕的名字打码、账号编号藏起来，雾幕认不出主播本人。现在按头像认，主播的弹幕照样带「主播」标签。
  When not logged in, Bilibili hides the sender's account id, so the streamer's own messages lost the streamer tag. The streamer is now recognised by avatar.
- 点歌姬用「音乐客户端」放歌时，叫网易云 / QQ 音乐最小化打开、不抢前台，免得全屏游戏被切出去（客户端听不听由它自己决定）；设置里也提示打游戏时用「雾幕自己放」。
  In music-client mode, NetEase / QQ Music is asked to open minimized without taking focus, so fullscreen games are not interrupted (it is up to the client to honour this).

---

## v0.9.15.3 · 2026-11-28

- 雾幕重启后读回来的弹幕丢了荣耀等级（灰色粉丝牌、回复了谁也一起丢了），现在都能读回来。0.9.15.2 的「荣耀等级回来了」只修了一半，这次才是真正的原因。
  Danmaku restored after a restart lost their honor (wealth) level, grey-medal state and reply target. They are kept now; 0.9.15.2 only fixed half of this.

---

## v0.9.15.2 · 2026-11-28

- 弹幕的「简洁」模式下荣耀等级也照常显示（0.9.15 会把它藏起来）。
  Honor (wealth) levels show again in the compact danmaku view (0.9.15 hid them).
- 「简洁」默认改成不开，0.9.15 默认开着的也先关上；想要可以再开。
  The compact view is now off by default, and is switched off once for anyone who had the 0.9.15 default.
- 「简洁模式」改成一个总开关，放在 设置 → 弹幕 最上面。
  The compact view is now a single switch at the top of Settings → Danmaku.

---

## v0.9.15.1 · 2026-11-27

只修问题、没有新功能的小更新。以后这类更新都在版本号后面加一位（0.9.15.1、0.9.15.2……）。
A bug-fix-only update. From now on, updates like this add a fourth number to the version (0.9.15.1, 0.9.15.2, ...).

- SC 攒到几百条时页面会越来越卡：现在先只显示最近的，更早的点「还有 N 条更早的」再展开。
  The page no longer slows down when hundreds of Super Chats pile up: only recent ones are shown, older ones expand on demand.
- 点歌姬切歌、拖进度时日志里不再记一大段报错。
  Switching or seeking songs no longer writes a long error to the log.
- 更新检查认得四位的版本号。注意：0.9.15 及更早的版本认不出 0.9.15.1，不会提示这次更新（等下一个大版本会正常提示），想要的话手动下载。
  The update check understands four-part versions. Note: 0.9.15 and earlier cannot see 0.9.15.1 and will not be notified; download it manually if you want it.

---

## v0.9.15 · 2026-11-27

### 独立软件 · A real desktop app

- 雾幕有了自己的窗口（用 Windows 自带的 WebView2），不再借 Edge 的窗口：标题栏、任务栏图标都是雾幕的，记得窗口大小和位置；以前窗口里的设置第一次会自动搬过来。少数电脑开不起来时自动退回原来的 Edge 窗口。
  Danmist now runs in its own window (Windows' built-in WebView2) instead of an Edge app window, with its own title bar and taskbar icon, and remembers its size and position. Settings carry over; it falls back to the Edge window if WebView2 is unavailable.
- 安装程序改成正经的安装向导：选位置、创建桌面 / 开始菜单快捷方式、进度条、装完启动雾幕。
  The installer is now a proper setup wizard with install location, shortcut options, a progress bar and a launch option.
- 软件窗口里右键是雾幕自己的菜单，Ctrl+P 打印这类浏览器快捷键不再起作用。
  Right-click shows Danmist's own menu, and browser shortcuts like Ctrl+P are disabled in the app window.

### 点歌 · Song requests

- 「点歌」二选一：**歌回点歌**（记进点歌单，主播来唱）或**点歌姬**（直接放）。点歌栏的页签带数字。
  Choose what 「点歌」 does: a **sing list** for you, or the **song bot** that plays it. Tabs show counts.
- 点歌姬：
  The song bot:
  - 雾幕自己出声，主播也听得到；也能叫电脑上的网易云或 QQ 音乐客户端放。OBS 放歌源改成可选。
    Plays from the app itself so you hear it too, or through the NetEase / QQ Music desktop client. The OBS audio source is now optional.
  - 登录音乐账号改成弹出官网登录页，像平常一样登录（以前扫码常被平台拦）。
    Music accounts log in through the official website in a pop-up window (QR login was often blocked).
  - 自动回观众一句（已点、前面几首、没找到、不合规则、已取消），可以关。
    Optional chat replies: queued with position, not found, rule not met, cancelled.
  - 放错版本能「换」一首；主播能自己搜歌加进去；能拖动排序；观众发「取消点歌」撤回。
    Swap a wrongly matched version, add songs yourself, drag to reorder; viewers can send 「取消点歌」.
  - 一个平台找不到或只能试听就自动换另一个平台；也能指定「点歌 qq 歌名」。
    Falls back to the other platform when a song is missing or preview-only; viewers can force one with 「点歌 qq …」.
  - 冷却：同一个人隔几秒、同一首几分钟内不再点。
    Cooldowns per viewer and per song.
  - 没人点时从曲库或网易云歌单里随机放；音量条、渐入渐出、响度均衡。
    Idle playlist from your library or a NetEase playlist; volume slider, fades and loudness normalization.
  - 歌词跟着放的歌上 OBS 歌词源；能点 B 站视频（点歌 BV号）。
    The OBS lyrics source follows the playing song; viewers can request a Bilibili video's audio by BV id.

### 界面 · Interface

- 顶栏：常用的几个按钮带字放外面（OBS、朗读、历史、曲库，可以自己挑），其余在「更多」里。
  Top bar: a few labeled buttons (your choice), the rest under "More".
- 弹幕「简洁」（默认开）：名字前只留舰长和自己直播间的粉丝牌。
  "Simple" danmaku (on by default): only guard and your own fan medal before names.
- 数据条上有最近 60 分钟的小曲线；第一次用时右下角有「开始用」清单。
  Sparklines on the stats bar; a getting-started checklist for new users.
- 设置页：不常用的折进「更多设置」，说明收成「?」；浅色模式的灰字更清楚。
  Settings fold rarely used groups and hide explanations behind "?"; better contrast in light mode.
- 功能页改成图片卡片，跟着深浅色和主题色；更新页减字。SC 卡片有深色模式。
  The feature guide uses illustrated cards that follow theme and accent; SC cards have a dark mode.

### 手机 · Phone

- 手机上滑弹幕不再被拽回最底下，也不会一碰就弹出观众卡片（点名字、头像才打开）。
  Scrolling danmaku on phones no longer snaps back or pops open viewer cards (tap the name or avatar).
- 「功能 / 更新」页在 iPhone 上能关了。
  The feature / updates page can be closed on iPhone again.

### 其他 · Other

- 软件内更新先测速，选最快的地址，太慢马上换；GitHub 连不上时也能提示有新版本。
  In-app updates pick the fastest mirror and switch when slow; new versions are announced even when GitHub is unreachable.
- 修：0.9.13 起改直播间标题、开播后收不到成功 / 失败提示。
  Fixed: no feedback after editing the room title or going live (since 0.9.13).

### 怎么更新 · How to update

顶栏点「下载更新」→「重启生效」，或者下载新的安装包直接装（存档、设置都保留）。从 0.9.14 及更早的版本用软件内更新过来，要到下一次更新才换成独立窗口（之前还是 Edge 窗口，功能都一样）；想马上用独立窗口就用安装包装一次。
Click **download update** → **restart**, or run the new installer (your data is kept). Updating in-app from 0.9.14 or older keeps the Edge window until the next update; run the installer once to get the new window right away.

---

## v0.9.14 · 2026-11-26

### 桌面版 · Desktop app

- 安装时可以选装到哪个文件夹（默认还是不用管理员的 `%LOCALAPPDATA%\Programs\Danmist`），选要不要建桌面、开始菜单快捷方式，装完要不要马上打开。升级时还装在原来的地方。
  The installer lets you choose the install folder (default `%LOCALAPPDATA%\Programs\Danmist`, no admin), whether to create desktop / Start menu shortcuts, and whether to launch afterwards. Upgrades stay in place.
- 设置 → 更多 → 软件：显示程序和存档在哪个文件夹，点「打开」直接打开。
  Settings → More → App shows where the program and your data live, with Open buttons.
- 雾幕的窗口（和抖音用的隐藏窗口）不再带上你 Edge 里装的扩展：以前 Edge 会把电脑上的账号和扩展同步进来，每次打开雾幕扩展就弹出来。
  The app window (and the hidden Douyin window) no longer loads your Edge extensions; Edge used to sync your account and extensions into it, so they popped up on every launch.
- 桌面版不再提示「装到桌面」（那是网页版用的）；界面里不再让你去看 README、改 config.json、双击 start.bat。
  The desktop app no longer offers "install to desktop" (a web-version thing), and the UI no longer sends you to the README or config.json.

### 账号 · Accounts

- 新的「设置 → 账号」：可以登好几个 B 站号，选哪个连直播间（观众名字不打码）、哪个发弹幕，随时换、随时退出。没登录时显示「游客」（以前写「默认账号」）。发送框左边的头像点进来就是这一页。
  New Settings → Accounts: log in several Bilibili accounts, pick which one connects to the room (unmasked names) and which one sends danmaku, switch or log out any time. Shows "Guest" when not logged in.

### 直播间 · Live room

- 「设置 → 直播间」：房间号框太窄填不进去的问题修好了；多了「切换直播间」名单（看、删、加，能粘网址），「同时收其他平台的弹幕」也挪到这里。
  Settings → Room: the room box is usable again; it now also holds the "switch room" list and "other platforms".
- 切换直播间的按钮从弹幕栏挪到顶栏。主播名字不用再自己写，会自动去 B 站查。
  The switch-room button moved to the top bar, and the streamer name is fetched from Bilibili automatically.
- 普通链接、管理链接这些给别人用的东西都归到「设置 → 链接」，「普通链接也能切直播间」的开关也在那里。
  Sharing links and the "public link can switch rooms" toggle are grouped under Settings → Links.

### 其他 · Other

- 身份标签：B 站自带的身份（总督、提督、舰长、房管等）名字固定，只改标签上显示的字和颜色；自己的标签能删了（以前删除按钮是看不见的）；改了自动保存；列出手动标成机器人的号。
  Identity tags: built-in roles keep their names (edit only the label text and color); custom tags can be deleted again; changes save automatically; manually marked bots are listed.
- AI 音色：音色在「设置 → 朗读 → AI 音色」里加，点「选…」用 Windows 的选文件窗口选参考音频和模型文件。
  AI voices are added in Settings → TTS → AI voices, with a native file picker for the reference clip and model files.

### 怎么更新 · How to update

顶栏点「下载更新」→「重启生效」，或者下载新的安装包直接装（存档、设置都保留）。
Click **download update** → **restart**, or run the new installer (your data is kept).

---

## v0.9.13 · 2026-11-26

### 直播间 · Live room

- 第一次打开不再问直播间号：软件里出一张卡片，选平台（B 站 / 斗鱼 / 虎牙 / 抖音）、填房间号。填错了在「设置 → 直播间」随时换，保存后自己重启连过去。
  No more room prompt on first launch: a card in the app lets you pick the platform (Bilibili / Douyu / Huya / Douyin) and enter the room. Change it any time in Settings → Live room; it restarts and reconnects by itself.
- 可以直接粘贴整段直播间网址，平台也会自动选对。B 站会先显示主播名和直播间标题让你确认，免得把 UID 当成房间号。
  You can paste the whole live-room URL and the platform is picked for you. For Bilibili, the streamer name and room title are shown for confirmation first, so a UID isn't mistaken for a room number.
- 切换到别的直播间的菜单做大了，也能选斗鱼、虎牙、抖音。
  The "switch room" menu is bigger and also offers Douyu, Huya and Douyin.

### 新功能 · New

- 身份标签自定义（设置 → 弹幕 → 身份标签）：舰长 / 提督 / 总督 / 房管 / 机器人 / 主播的名字、简称、颜色都能改；还能建自己的标签，在观众卡片里给人加上，或者标成机器人。
  Custom identity tags: rename and recolor captain / admiral / governor / moderator / bot / streamer tags, create your own tags, and assign them (or mark bots) from the viewer card.
- 一键备份 / 恢复：设置 → 更多 → 备份。立即备份、从某一份恢复（先备份现在的，再重启换上）、打开备份文件夹。软件内更新前会自动备份一份。
  One-click backup / restore in Settings → More → Backup. Backs up automatically before an in-app update.
- OBS 歌词源：歌单里「正在唱」的那首歌词上屏，有时间轴就跟着走。OBS 设置页多了「歌词」。
  OBS lyrics source: shows the lyrics of the song marked "singing now"; timed lyrics follow the timeline. New "Lyrics" tab in the OBS setup page.
- OBS 弹幕新选项：一段时间没人说话整列隐藏、SC 停留多久、表情包大小、进房提示只显示提督以上 / 只总督。
  New OBS overlay options: hide when idle, SC display time, sticker size, entry banners for admiral+ / governor only.
- 声音从哪出：设置 → 朗读，AI 朗读、提示音和这页放的歌可以选输出设备，比如只进耳机、不进直播。
  Audio output device: in Settings → TTS, AI voice, alert sounds and in-page music can go to a chosen device (e.g. headphones only).
- AI 音色（GPT-SoVITS）的地址在 设置 → 朗读 里填，保存时马上测连不连得上。
  Set the GPT-SoVITS address in Settings → TTS; it is tested when you save.
- 换看板娘以后，桌面和开始菜单的快捷方式图标也跟着换。
  After changing the mascot, the desktop and Start menu shortcut icons change too.
- 设置 → 更多 → 导出诊断信息：出问题时把这个发给作者（密钥、Cookie 会自动藏掉）。
  Settings → More → Export diagnostics, with keys and cookies redacted.

### 改进 · Improvements

- 软件内更新：GitHub 下载不了时自动换国内加速站，下完按 GitHub 给的 sha256 核对；都不行会提示去百度网盘下。
  In-app updates fall back to mirror sites when GitHub is unreachable and verify the sha256 published by GitHub; if all fail, it points to the Baidu Netdisk mirror.
- 抖音：隐藏的浏览器不再下载直播视频，省 CPU、显卡和网速；抖音要验证或者页面上找不到聊天区时，那一行亮黄字并弹提醒。
  Douyin: the hidden browser no longer downloads the video stream; if Douyin asks for verification or the chat area disappears, the row turns yellow and you get a notice.
- 断流后 5 分钟内重新开播算同一场。
  Restarting the stream within 5 minutes continues the same session.
- AI 音色、网易云 / QQ 音乐、B 站名片这些外部服务连续失败时先歇一会再试，不再一直卡着。
  External services (AI voice, music, Bilibili profile cards) back off after repeated failures.

### 安全 · Security

- 经 Nginx、frp、ngrok 这类转发进来的访问不再被当成「在这台电脑上打开」，要用管理链接才有管理权限。
  Requests arriving through a reverse proxy (Nginx, frp, ngrok…) are no longer treated as local; they need an admin link.
- 图片缓存最多占 500MB，超了先删最久没看的。抖音浏览器的调试口只开在本机。
  Image cache is capped at 500 MB. The Douyin browser's debug port listens on localhost only.

### 怎么更新 · How to update

顶栏点「下载更新」→「重启生效」。更早的版本见 README「更新到新版本」。
Click **download update** → **restart**. Older versions: see "Updating to a new version" in the README.

---

## v0.9.12 · 2026-11-26

### 抖音 · Douyin

- 同时在抖音开播时，抖音直播间的弹幕、进房、礼物也能收进雾幕：设置 → 弹幕 → 其他平台，选「抖音」，填直播间网址 live.douyin.com/ 后面那串数字。每条标「抖音」，OBS 上也标。
  Douyin live rooms are supported: Settings → Danmaku → Other platforms → Douyin, enter the number after live.douyin.com/. Messages are tagged "抖音", on the OBS overlay too.
- 不碰抖音的接口和签名：雾幕在这台电脑上开一个放在屏幕外面、看不见的浏览器窗口，像人一样打开直播间网页，把页面上显示出来的读出来。所以只能在装了 Edge 或 Chrome 的 Windows 电脑上用（桌面版、安装版就是这样）。
  It doesn't touch Douyin's APIs or signatures: an off-screen browser window on this PC opens the live room like a person would and reads what the page shows. Requires Windows with Edge or Chrome.
- 不登录抖音时观众名字会打码。点那一行的「显示窗口」，在弹出来的窗口里登录抖音（或者过验证），弄好点「藏起来」；登录会记住。抖音网页不登录时基本不显示礼物，礼物要登录后才收得到。
  Names are masked until you log in to Douyin: click "Show window", log in (or pass a check) in that window, then "Hide". The login is remembered. Gifts mostly only show on the Douyin web page when logged in.

### 其他 · Other

- 免安装包改名 `Danmist-vX.Y.Z-windows-x64.zip`（以前叫 bili-danmaku-board-…），软件内更新照样能找到。Release 里多了一份给网盘用户的简单说明（Danmist-README-CN.txt）。
  The portable zip is renamed to `Danmist-vX.Y.Z-windows-x64.zip`; in-app updates still find it. Releases now include a short Chinese readme for download mirrors.

### 怎么更新 · How to update

v0.9.5 起：顶栏点「下载更新」→「重启生效」。更早的版本见 README「更新到新版本」。
From v0.9.5: click **download update** → **restart**. Older versions: see "Updating to a new version" in the README.

---

## v0.9.11 · 2026-11-26

### 新功能 · New

- 换看板娘：设置 → 更多 → 看板娘，上传自己的图，软件里的图标、窗口和任务栏图标都换成它（不是正方形会从中间裁），随时能换回默认。「关于」里不变；桌面快捷方式的图标换不了。
  Custom mascot: Settings → More → Mascot. Upload your own picture to replace the in-app, window and taskbar icons (non-square images are center-cropped); you can switch back any time. The desktop shortcut icon is not changed.

### 修复 · Fixes

- 鼠标停在弹幕栏上时，用键盘或拖滚动条往上翻，2 秒后会被拽回最底下。现在只要是自己往上翻（PageUp / ↑ / Home、拖滚动条、滚轮、手指），就一直停在那里，赶上进房提示弹出也一样。
  Scrolling up with the keyboard or scrollbar while the mouse rested on the list snapped back to the bottom after 2 seconds. Manual scrolling now always holds, even while an entry notice pops up.

### 怎么更新 · How to update

v0.9.5 起：顶栏点「下载更新」→「重启生效」。更早的版本见 README「更新到新版本」。
From v0.9.5: click **download update** → **restart**. Older versions: see "Updating to a new version" in the README.

---

## v0.9.10 · 2026-11-25

### 修复 · Fixes

- 弹幕满 300 条以后不再自动跟随、一直显示「↓ n 条新弹幕」：原因是弹幕多了会删掉最上面的旧弹幕，浏览器这时把滚动位置往回调，被误当成人在往上翻。现在只有真的用滚轮、键盘、鼠标或手指往上翻才暂停跟随（感谢 nana 的反馈和分析）。v0.9.9 只修了鼠标停在弹幕栏上那一种情况。
  Danmaku stopped following after the list reached 300 rows and showed "↓ n new" instead: trimming old rows made the browser adjust the scroll position, which was mistaken for the user scrolling up. Following now only pauses on real input (wheel, keyboard, mouse, touch). Thanks to nana for the report and analysis. v0.9.9 only fixed the mouse-hover case.

### 怎么更新 · How to update

v0.9.5 起：顶栏点「下载更新」→「重启生效」。更早的版本见 README「更新到新版本」。
From v0.9.5: click **download update** → **restart**. Older versions: see "Updating to a new version" in the README.

---

## v0.9.9 · 2026-11-25

### 修复 · Fixes

- 弹幕栏在最底下时，观众的新弹幕有时不自动跟上，变成「↓ n 条新弹幕」要自己去滚：原因是鼠标只要停在弹幕栏上就一直暂停跟随。现在只有鼠标在弹幕上移动时才暂停，停着不动 2 秒就接着跟到最新，暂停时也不再弹「新弹幕」条。
  New danmaku sometimes stopped following at the bottom and showed "↓ n new" instead: resting the mouse over the list paused following indefinitely. Now it only pauses while the mouse moves, resumes after 2 idle seconds, and doesn't show the "new" bar while paused.
- 自己扫码登录的号发的弹幕不再标「机器人」（也不再被当成机器人跳过朗读、点歌）。只有在 `config.json` 里另外接了机器人（`bot_say_url`）时，连直播间的号才算机器人。
  Danmaku from your own logged-in account are no longer tagged as "bot" (or skipped by text-to-speech and song requests). The room-connection account only counts as a bot when a separate bot is configured via `bot_say_url`.

### 怎么更新 · How to update

v0.9.5 起：顶栏点「下载更新」→「重启生效」。更早的版本见 README「更新到新版本」。
From v0.9.5: click **download update** → **restart**. Older versions: see "Updating to a new version" in the README.

---

## v0.9.8 · 2026-11-25

### 斗鱼、虎牙 · Douyu and Huya

- 同时在斗鱼、虎牙开播时，可以把那边的弹幕、礼物、进房也收进雾幕：设置 → 弹幕 → 「其他平台」里加房间号。每条前面标「斗鱼」「虎牙」，OBS 弹幕上也标；点歌、朗读跟 B 站的一样处理。只读，不会用你的账号发任何东西。
  If you also stream on Douyu or Huya, add those rooms under Settings → Danmaku → Other platforms. Their danmaku, gifts and entries appear alongside Bilibili's, tagged with the platform (on the OBS overlay too). Read-only.
- 抖音暂时没做：抖音的弹幕要过它自己的反爬签名，绕过它不合适。
  Douyin is not supported: its live chat sits behind anti-bot signing that we won't bypass.

### 点歌放歌 · Song requests

- 扫码登不上时，可以「粘贴登录信息」：在电脑浏览器登录网易云 / QQ 音乐网页版，复制 Cookie 粘进来。「电脑上的网易云」模式用客户端自己的登录，雾幕这边不用登录。
  If QR login fails, paste the cookie from the NetEase / QQ Music website instead. In "desktop NetEase" mode the client's own login is used.

### 文档 · Docs

- README 写清了老版本（v0.9.0–v0.9.4）怎么更新，以及从免安装版搬到安装版时怎么把存档带过去。
  The README now explains how to update from v0.9.0–v0.9.4 and how to move your archives to the installed version.

### 怎么更新 · How to update

v0.9.5 起：顶栏点「下载更新」→「重启生效」。更早的版本：下载安装包直接装（再按 README 把 config.json 和 data 拷过去），或者下载 zip 解压覆盖。
From v0.9.5: click **download update** → **restart**. Older versions: run the installer (then copy `config.json` and `data` over as described in the README), or extract the zip over your folder.

---

## v0.9.7 · 2026-11-25

### 新图标和看板娘 · New icon and mascot

- 图标换成带看板娘的定稿版（雾冬Hanaki 坐在左下角，小尺寸自动用不带小人的版本）。设置 → 更多 → 「关于」里能看到版本号和看板娘的直播间。
  The icon now shows the mascot 雾冬Hanaki in the corner (small sizes use a plain version). Settings → More → About shows the version and the mascot's live room.

### 怎么更新 · How to update

v0.9.5 起：顶栏点「下载更新」→「重启生效」。更早的版本：下载安装包直接装，或者下载 zip 解压覆盖。
From v0.9.5: click **download update** → **restart** in the top bar. Older versions: run the installer, or extract the zip over your folder.

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
