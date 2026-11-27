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


def show(url, title="雾幕"):
    """开窗口，一直到窗口关掉才返回。返回 True = 窗口正常开过；False = 开不起来（启动器换 Edge）"""
    try:
        import webview
    except Exception:
        return False
    set_app_id()
    carry_over_storage()
    st = load_state()
    shown = threading.Event()
    # 点歌姬由雾幕自己出声（2026-11-26 用户：主播也要听到）：不用先点一下页面也能放
    os.environ.setdefault('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', '--autoplay-policy=no-user-gesture-required')
    try:
        webview.settings['ALLOW_DOWNLOADS'] = True                  # 导出诊断信息、导出设置这些要能下载
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True   # GitHub、B 站这些链接用平时的浏览器开
    except Exception:
        pass
    win = webview.create_window(title, url, width=st['width'], height=st['height'], x=st['x'], y=st['y'],
                                min_size=(900, 600), background_color='#111925', text_select=True)

    def before_show(window=None):
        try:  # 窗口和任务栏的图标
            import clr  # noqa: F401
            from System.Drawing import Icon
            win.native.Icon = Icon(icon_path())
        except Exception:
            pass

    def loaded():
        shown.set()

    def closing():
        save_state(win)

    try:
        win.events.before_show += before_show
    except Exception:
        pass
    win.events.loaded += loaded
    win.events.closing += closing
    try:
        webview.start(gui='edgechromium', private_mode=False, storage_path=STORE, debug=False)
    except Exception:
        return False
    return shown.is_set()
