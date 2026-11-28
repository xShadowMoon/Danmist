"""雾幕自己的软件窗口（2026-11-26 用户：要完整的独立软件，不靠 Edge）。

用 Windows 自带的 WebView2（Win10 / Win11 都有）显示雾幕的页面：窗口、标题栏、任务栏图标都是雾幕自己的，
不会再带上 Edge 的扩展、账号和地址栏。界面还是同一套网页，所以功能一样。

开不起来（没装 WebView2、缺组件）时 show() 返回 False，启动器就照旧用 Edge 的应用窗口。
"""
import json
import os
import shutil
import sys
import threading
import time

APP = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(APP, 'data')
STATE = os.path.join(DATA, 'window.json')     # 上次关窗口时的大小和位置
STORE = os.path.join(DATA, 'webview')         # 网页的设置、登录过的号（localStorage）存在这里


def available():
    if sys.platform != 'win32':
        return False
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def icon_path():
    """换过看板娘就用换的图标"""
    try:
        mine = sorted(n for n in os.listdir(os.path.join(DATA, 'mascot')) if n.startswith('mascot-') and n.endswith('.ico'))
        if mine:
            return os.path.join(DATA, 'mascot', mine[-1])
    except OSError:
        pass
    return os.path.join(APP, 'static', 'art', 'icon.ico')


def load_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            s = json.load(f)
        w, h = int(s.get('w', 1400)), int(s.get('h', 900))
        x, y = s.get('x'), s.get('y')
        return {'width': max(900, min(w, 7680)), 'height': max(600, min(h, 4320)),
                'x': int(x) if isinstance(x, int) and -10000 < x < 20000 else None,
                'y': int(y) if isinstance(y, int) and -10000 < y < 20000 else None}
    except (OSError, ValueError, TypeError):
        return {'width': 1400, 'height': 900, 'x': None, 'y': None}


def save_state(win):
    try:
        s = {'w': int(win.width), 'h': int(win.height), 'x': int(win.x), 'y': int(win.y)}
        if s['w'] < 300 or s['h'] < 200:  # 最小化的时候关的：不记
            return
        os.makedirs(DATA, exist_ok=True)
        with open(STATE, 'w', encoding='utf-8') as f:
            json.dump(s, f)
    except Exception:
        pass


def carry_over_storage():
    """以前用 Edge 窗口时的设置（主题、布局、登录过的号）在 data/desktop-browser 里：第一次换成自己的窗口时搬过来"""
    old = os.path.join(DATA, 'desktop-browser', 'Default', 'Local Storage')
    new = os.path.join(STORE, 'EBWebView', 'Default', 'Local Storage')
    if os.path.isdir(old) and not os.path.exists(new):
        try:
            shutil.copytree(old, new, ignore=shutil.ignore_patterns('LOCK'))
        except OSError:
            pass


def set_app_id():
    """任务栏上单独一组、用雾幕的图标（不跟别的 Python 程序挤在一起）"""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('xShadowMoon.Danmist')
    except Exception:
        pass


SHOW_EVENT = 'Local\\Danmist-Show-{}'  # 再双击一次雾幕时，叫已经开着的那个窗口出来（2026-11-28）


def signal_running(port):
    """已经开着一个雾幕了：叫它把窗口拿出来。叫到了返回 True（这边就不用再开窗口）"""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.OpenEventW.restype = ctypes.c_void_p
        h = k32.OpenEventW(0x0002, False, SHOW_EVENT.format(port))  # EVENT_MODIFY_STATE
        if not h:
            return False
        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # 让那边的窗口能跳到最前面
        ok = bool(k32.SetEvent(ctypes.c_void_p(h)))
        k32.CloseHandle(ctypes.c_void_p(h))
        return ok
    except Exception:
        return False


def wait_show_requests(port, on_show):
    """在后台等「再双击了一次雾幕」的信号"""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.CreateEventW.restype = ctypes.c_void_p
        h = k32.CreateEventW(None, False, False, SHOW_EVENT.format(port))
        if not h:
            return
    except Exception:
        return

    def loop():
        while True:
            if k32.WaitForSingleObject(ctypes.c_void_p(h), 0xFFFFFFFF) == 0:
                on_show()
    threading.Thread(target=loop, daemon=True).start()


def log(text):
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(os.path.join(DATA, 'desktop.log'), 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')
    except OSError:
        pass


def show(url, title="雾幕", port=None, hidden=False, status=None, close_mode=None):
    """开窗口，一直到窗口关掉（退出雾幕）才返回。返回 True = 窗口正常开过；False = 开不起来（启动器换 Edge）
    2026-11-28：右下角托盘图标；关窗口缩到托盘（close_mode() 返回 'quit' 时直接退出）；hidden=True 开机自启时只放在托盘里；
    status() 给托盘看的雾幕状态；下载用雾幕自己的保存窗口，不弹 Edge 的下载面板；Ctrl+滚轮不缩放"""
    try:
        import webview
    except Exception:
        return False
    set_app_id()
    carry_over_storage()
    st = load_state()
    shown = threading.Event()
    box = {'tray': None, 'hooked': False}
    # 点歌姬由雾幕自己出声（2026-11-26 用户：主播也要听到）：不用先点一下页面也能放
    os.environ.setdefault('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', '--autoplay-policy=no-user-gesture-required')
    try:
        webview.settings['ALLOW_DOWNLOADS'] = True                  # 导出诊断信息、导出设置这些要能下载
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True   # GitHub、B 站这些链接用平时的浏览器开
    except Exception:
        pass
    base = url.split('?')[0]

    class Api:
        """页面里能叫的（window.pywebview.api.xxx）"""
        def popout(self):
            """弹幕小窗（2026-11-28：以前在软件里点会弹「找不到能打开 about 链接的应用」再开个浏览器）：在雾幕里开一个浮在最上面的小窗"""
            for w in list(webview.windows):
                if getattr(w, 'title', '') == '弹幕小窗':
                    w.show()
                    return True
            webview.create_window('弹幕小窗', base + '?pop=1&app=1', width=420, height=680, min_size=(280, 300),
                                  on_top=True, background_color='#111925', text_select=True)
            return True

    win = webview.create_window(title, url, width=st['width'], height=st['height'], x=st['x'], y=st['y'],
                                min_size=(900, 600), background_color='#111925', text_select=True, hidden=hidden, js_api=Api())

    def tray_ok():
        return box['tray'] is not None and box['tray'].ni is not None

    def on_form_closing(sender, e):
        """点 ✕：缩到托盘（关机、注销时照常关）"""
        try:
            from System.Windows.Forms import CloseReason
            t = box['tray']
            if not tray_ok() or t.quitting or e.CloseReason != CloseReason.UserClosing:
                return
            if (close_mode() if close_mode else 'tray') != 'tray':
                return
            e.Cancel = True
            save_state(win)
            sender.Hide()
            t.hidden_to_tray()
        except Exception as ex:
            log(f'缩到托盘出错：{ex}')

    def before_show(window=None):
        try:  # 窗口和任务栏的图标
            import clr  # noqa: F401
            from System.Drawing import Icon
            win.native.Icon = Icon(icon_path())
        except Exception:
            pass
        try:
            import tray
            t = tray.Tray(win, title, icon_path())
            t.build()
            box['tray'] = t
            win.native.FormClosing += on_form_closing
        except Exception as ex:
            log(f'托盘图标没做起来：{ex}')

    def on_download(sender, args):
        """下载（导出诊断信息、导出设置）：保存窗口是 pywebview 弹的，这里把 Edge 自己的下载面板藏掉，存好了在雾幕里说一声"""
        try:
            if args.Cancel:
                return
            args.Handled = True
            op, path = args.DownloadOperation, str(args.ResultFilePath)

            def changed(s, e):
                try:
                    state = str(op.State)
                    if state == 'Completed':
                        code = f"typeof note === 'function' && note({json.dumps('已保存：' + path)}, true)"
                    elif state == 'Interrupted':
                        code = "typeof note === 'function' && note('没保存成功，换个文件夹再试', false)"
                    else:
                        return
                    threading.Thread(target=lambda: win.evaluate_js(code), daemon=True).start()
                except Exception:
                    pass
            op.StateChanged += changed
        except Exception as ex:
            log(f'下载处理出错：{ex}')

    def hook_webview():
        if box['hooked']:
            return
        core = win.native.browser.webview.CoreWebView2
        if core is None:
            return
        box['hooked'] = True
        s = core.Settings
        for k in ('IsZoomControlEnabled', 'IsPinchZoomEnabled', 'IsSwipeNavigationEnabled'):
            try:
                setattr(s, k, False)  # 不像浏览器：Ctrl+滚轮、双指缩放、左右滑动翻页都关掉
            except Exception:
                pass
        core.DownloadStarting += on_download

    def loaded():
        shown.set()
        try:
            from System import Action
            win.native.BeginInvoke(Action(lambda: hook_webview()))
        except Exception as ex:
            log(f'窗口设置没改上：{ex}')

    def closing():
        save_state(win)

    def bring_up():
        t = box['tray']
        if t is not None:
            t.ui(t.open)

    def watch_status():
        while status:
            try:
                time.sleep(5)
                t = box['tray']
                if t is not None and t.ni is not None:
                    t.update_status(status())
            except Exception:
                pass

    try:
        win.events.before_show += before_show
    except Exception:
        pass
    win.events.loaded += loaded
    win.events.closing += closing
    if port:
        wait_show_requests(port, bring_up)
    if status:
        threading.Thread(target=watch_status, daemon=True).start()
    try:
        webview.start(gui='edgechromium', private_mode=False, storage_path=STORE, debug=False)
    except Exception:
        return False
    finally:
        if box['tray'] is not None:
            box['tray'].remove()
    return shown.is_set() or hidden
