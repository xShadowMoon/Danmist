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

    def balloon(self, title, text):
        if self.ni is None:
            return
        from System.Windows.Forms import ToolTipIcon
        self.ni.ShowBalloonTip(6000, title, text, ToolTipIcon.Info)

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
