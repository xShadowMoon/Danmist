"""右下角托盘图标（2026-11-28 用户：要像正经软件一样，任务栏右下角能看到雾幕）。

只在雾幕自己的软件窗口（native_window.py）里用：Windows 自带的 NotifyIcon（WinForms），不用另外装东西。
- 一直显示雾幕的图标，鼠标放上去看到直播间和连接状态；左键点一下打开窗口
- 右键菜单：打开雾幕 / 弹幕小窗 / 检查更新 / 退出雾幕
- 关窗口时缩到这里（第一次弹个气泡说明）；有新版本、跟直播间断开太久时弹 Windows 通知
做不起来（缺组件）时什么都不做，窗口照常用。
"""
import os
import threading
import time

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
HINT_FILE = os.path.join(DATA, 'tray-hint-shown')  # 「关窗口缩到托盘」的说明只弹一次


def short(text, n=63):
    """托盘提示文字最多 63 个字（再长 Windows 会报错）"""
    text = str(text or '')
    return text if len(text) <= n else text[:n - 1] + '…'


class Tray:
    def __init__(self, win, title, icon_path):
        self.win = win
        self.title = title or '雾幕'
        self.icon_path = icon_path
        self.ni = None
        self.quitting = False
        self.notified_update = ''
        self.down_since = 0.0
        self.notified_down = False
        self.toasts = []

    # ---------- 下面这些都在窗口的界面线程里跑 ----------
    def build(self):
        import clr  # noqa: F401
        clr.AddReference('System.Windows.Forms')
        clr.AddReference('System.Drawing')
        from System.Drawing import Font, FontStyle, Icon
        from System.Windows.Forms import ContextMenuStrip, MouseButtons, NotifyIcon, ToolStripMenuItem, ToolStripSeparator
        ni = NotifyIcon()
        ni.Icon = Icon(self.icon_path)
        ni.Text = short(self.title)
        menu = ContextMenuStrip()

        def item(text, fn, bold=False):
            it = ToolStripMenuItem(text)
            if bold:
                it.Font = Font(it.Font, FontStyle.Bold)
            it.Click += lambda s, e: self.safe(fn)
            menu.Items.Add(it)
        item('打开雾幕', self.open, bold=True)
        item('弹幕小窗', self.popout)
        item('检查更新', self.check_update)
        menu.Items.Add(ToolStripSeparator())
        item('退出雾幕', self.quit)
        ni.ContextMenuStrip = menu
        ni.MouseClick += lambda s, e: self.safe(self.open) if e.Button == MouseButtons.Left else None
        ni.BalloonTipClicked += lambda s, e: self.safe(self.open)
        ni.Visible = True
        self.ni = ni

    def safe(self, fn):
        try:
            fn()
        except Exception:
            pass

    def form(self):
        return self.win.native

    def open(self):
        from System.Windows.Forms import FormWindowState
        f = self.form()
        f.Show()
        if f.WindowState == FormWindowState.Minimized:
            f.WindowState = FormWindowState.Normal
        f.Activate()

    def popout(self):
        self.open()
        self.js("document.getElementById('dmpop') && document.getElementById('dmpop').click()")

    def check_update(self):
        self.open()
        self.js("typeof openSettings === 'function' && openSettings('more'); document.getElementById('dkcheck') && document.getElementById('dkcheck').click()")

    def quit(self):
        self.quitting = True
        self.remove()
        try:  # 弹幕小窗这些别的窗口一起关
            import webview
            for w in list(webview.windows):
                if w is not self.win:
                    w.destroy()
        except Exception:
            pass
        self.form().Close()

    def remove(self):
        if self.ni is not None:
            try:
                self.ni.Visible = False
                self.ni.Dispose()
            except Exception:
                pass
            self.ni = None

    def hidden_to_tray(self):
        """关窗口缩到托盘以后：第一次弹个气泡告诉主播雾幕还在"""
        if os.path.exists(HINT_FILE):
            return
        self.balloon('雾幕还在后台运行', '弹幕、朗读、点歌都照常。要彻底关掉：右键这个图标 →「退出雾幕」')
        try:
            os.makedirs(DATA, exist_ok=True)
            with open(HINT_FILE, 'w', encoding='utf-8') as f:
                f.write(time.strftime('%Y-%m-%d %H:%M:%S'))
        except OSError:
            pass

    def balloon(self, title, text, seconds=8):
        """右下角弹一个雾幕自己的小通知（2026-11-28：Windows 的气泡通知打游戏时会被免打扰挡掉，用户没看到）。
        不抢焦点，点一下打开雾幕，过几秒自己消失"""
        if self.ni is None:
            return
        import ctypes
        from System.Drawing import Color, Font, FontStyle, Point, Size
        from System.Windows.Forms import Form, FormBorderStyle, FormStartPosition, Label, Screen, Timer
        f = Form()
        f.FormBorderStyle = getattr(FormBorderStyle, 'None')
        f.ShowInTaskbar = False
        f.StartPosition = FormStartPosition.Manual
        f.BackColor = Color.FromArgb(27, 36, 52)
        f.Size = Size(360, 104)
        wa = Screen.PrimaryScreen.WorkingArea
        f.Location = Point(wa.Right - 372, wa.Bottom - 116 - 112 * len(self.toasts))
        t1, t2 = Label(), Label()
        t1.Text, t2.Text = title, text
        t1.ForeColor, t2.ForeColor = Color.White, Color.FromArgb(196, 208, 224)
        t1.Font = Font('Microsoft YaHei UI', 10.5, FontStyle.Bold)
        t2.Font = Font('Microsoft YaHei UI', 9.0)
        t1.Location, t1.Size = Point(16, 14), Size(328, 24)
        t2.Location, t2.Size = Point(16, 42), Size(328, 54)
        f.Controls.Add(t1)
        f.Controls.Add(t2)
        timer = Timer()
        timer.Interval = seconds * 1000

        def close(*_):
            try:
                timer.Stop()
                ctypes.windll.user32.ShowWindow(ctypes.c_void_p(h), 0)  # 不是用 Show() 显示的，Close() 关不掉：先藏再释放
                f.Dispose()
                timer.Dispose()
            except Exception:
                pass
            if f in self.toasts:
                self.toasts.remove(f)

        def click(*_):
            close()
            self.safe(self.open)
        for c in (f, t1, t2):
            c.Click += click
        h = int(str(f.Handle.ToInt64()))
        timer.Tick += close
        self.toasts.append(f)
        # 不抢焦点地显示在最上面：SWP_NOACTIVATE | SWP_SHOWWINDOW
        ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(h), ctypes.c_void_p(-1), f.Location.X, f.Location.Y, 360, 104, 0x0010 | 0x0040)
        timer.Start()

    # ---------- 后台线程用：转到界面线程去做 ----------
    def ui(self, fn):
        try:
            from System import Action
            self.form().BeginInvoke(Action(lambda: self.safe(fn)))
        except Exception:
            pass

    def js(self, code):
        """在页面里跑一句（不能在界面线程里等结果，放到后台线程）"""
        threading.Thread(target=lambda: self.safe(lambda: self.win.evaluate_js(code)), daemon=True).start()

    def update_status(self, st):
        """启动器每隔一会儿把雾幕后台的状态给过来：改提示文字、该提醒的弹通知"""
        if not isinstance(st, dict):
            return
        anchor = st.get('anchor') or ''
        live = '直播中' if st.get('live') == 1 else '未开播'
        conn = '已连接' if st.get('bili_ok') is not False else '没连上直播间'
        text = short(f"{self.title}{' · ' + anchor if anchor else ''} · {live} · {conn}")
        self.ui(lambda: setattr(self.ni, 'Text', text) if self.ni is not None else None)
        for tip in st.get('tips') or []:  # 点歌姬这些给主播的提醒（2026-11-28）
            if isinstance(tip, dict):
                self.ui(lambda tip=tip: self.balloon(str(tip.get('title') or '雾幕'), str(tip.get('text') or ''), 12))
        v = st.get('update') or ''
        if v and v != self.notified_update:
            self.notified_update = v
            self.ui(lambda: self.balloon(f'雾幕有新版本 v{v}', '点这里打开雾幕，在顶上点「下载更新」'))
        if st.get('bili_ok') is False and st.get('room'):
            self.down_since = self.down_since or time.time()
            if not self.notified_down and time.time() - self.down_since > 120:
                self.notified_down = True
                self.ui(lambda: self.balloon('和直播间断开了', '已经断开两分钟以上，雾幕一直在自己重连。网络正常的话可以重开一下雾幕'))
        else:
            if self.notified_down:
                self.ui(lambda: self.balloon('又连上直播间了', '弹幕恢复正常'))
            self.down_since, self.notified_down = 0.0, False


def ask_close(owner):
    """点 ✕ 时问一下（2026-11-28 用户：要弹窗选缩小还是退出，再加个「不再提醒」）。
    返回 (选的, 不再提醒)：选的是 'tray' / 'quit' / ''（点了取消或关掉这个框）"""
    from System.Drawing import Font, FontStyle, Point, Size
    from System.Windows.Forms import (Button, CheckBox, DialogResult, Form, FormBorderStyle, FormStartPosition, Label)
    f = Form()
    f.Text = '雾幕'
    f.FormBorderStyle = FormBorderStyle.FixedDialog
    f.MaximizeBox = f.MinimizeBox = False
    f.ShowInTaskbar = False
    f.StartPosition = FormStartPosition.CenterParent
    f.ClientSize = Size(420, 170)
    f.Font = Font('Microsoft YaHei UI', 9.5)
    try:
        f.Icon = owner.Icon
    except Exception:
        pass
    t1 = Label()
    t1.Text = '关掉窗口后，雾幕要怎么办？'
    t1.Font = Font('Microsoft YaHei UI', 11.0, FontStyle.Bold)
    t1.Location, t1.Size = Point(20, 18), Size(380, 26)
    t2 = Label()
    t2.Text = '缩到右下角托盘：弹幕、朗读、点歌照常，右键托盘图标能退出。'
    t2.Location, t2.Size = Point(20, 50), Size(380, 40)
    keep = CheckBox()
    keep.Text = '不再提醒（以后可以在 设置 → 更多 → 软件 里改）'
    keep.Location, keep.Size = Point(20, 92), Size(390, 24)
    b1, b2 = Button(), Button()
    b1.Text, b2.Text = '缩到托盘', '退出雾幕'
    b1.DialogResult, b2.DialogResult = DialogResult.Yes, DialogResult.No
    b1.Location, b1.Size = Point(196, 126), Size(100, 32)
    b2.Location, b2.Size = Point(304, 126), Size(100, 32)
    for c in (t1, t2, keep, b1, b2):
        f.Controls.Add(c)
    f.AcceptButton = b1
    r = f.ShowDialog(owner)
    choice = 'tray' if r == DialogResult.Yes else 'quit' if r == DialogResult.No else ''
    remember = bool(keep.Checked) and bool(choice)
    f.Dispose()
    return choice, remember
