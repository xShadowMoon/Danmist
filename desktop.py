"""雾幕桌面版启动器（2026-11-25）。

用法：python\\pythonw.exe desktop.py          软件窗口（默认）
      python\\pythonw.exe desktop.py --web    用浏览器打开（跟以前 start.bat 一样）
      python desktop.py --shortcut             在桌面建一个「雾幕」快捷方式

做的事：
1. 在后台开雾幕服务（server.py，没有黑窗口），日志写 data/server.log；
2. 服务起来后，用 Edge（没有就 Chrome）的「应用窗口」打开它 —— 没有地址栏、任务栏单独一个图标，
   看起来就是一个软件；用单独的配置文件夹 data/desktop-browser，不碰你平时的浏览器；
3. 窗口关掉，服务也一起停；
4. 页面上点了「重启生效」（软件内更新）：服务以退出码 75 退出，这里把下载好的新版本换上，再把服务开起来，
   窗口不用关，几秒后页面自己连回来、刷新成新版本。
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
import updates  # noqa: E402

NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0
TOKEN = secrets.token_hex(16)  # 关窗口时叫服务先存好再退用的口令


def config():
    try:
        with open(os.path.join(APP, 'config.json'), encoding='utf-8-sig') as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def say(text):
    """没有黑窗口时把话写进 data/desktop.log；有窗口就也打印出来"""
    os.makedirs(os.path.join(APP, 'data'), exist_ok=True)
    with open(os.path.join(APP, 'data', 'desktop.log'), 'a', encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')
    try:
        print(text, flush=True)
    except (OSError, ValueError, AttributeError):
        pass


def message(text):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, '雾幕', 0x40)
    else:
        say(text)


def python_exe():
    """服务用 python.exe（不是 pythonw）跑，这样崩了能在日志里看到原因；用 CREATE_NO_WINDOW 不出黑窗口"""
    exe = sys.executable
    if exe.lower().endswith('pythonw.exe'):
        exe = exe[:-len('pythonw.exe')] + 'python.exe'
    return exe


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(('127.0.0.1', port)) == 0


def start_server(port):
    os.makedirs(os.path.join(APP, 'data'), exist_ok=True)
    log = os.path.join(APP, 'data', 'server.log')
    env = dict(os.environ, BDB_LAUNCHER='1', BDB_TOKEN=TOKEN, PYTHONUTF8='1')
    return subprocess.Popen([python_exe(), os.path.join(APP, 'server.py'), '--log', log], cwd=APP, env=env,
                            creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_ready(port, proc, seconds=60):
    for _ in range(seconds * 5):
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/ping', timeout=1) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.2)
    return False


def find_browser():
    pf = [os.environ.get(k, '') for k in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA')]
    for base in pf:
        for rel in (r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe'):
            p = os.path.join(base, rel)
            if base and os.path.isfile(p):
                return p
    return None


def open_window(url):
    """Edge / Chrome 的应用窗口；都没有就用默认浏览器（这时没法知道窗口什么时候关）"""
    b = find_browser()
    if not b:
        import webbrowser
        webbrowser.open(url)
        return None
    prof = os.path.join(APP, 'data', 'desktop-browser')
    return subprocess.Popen([b, f'--app={url}', f'--user-data-dir={prof}', '--no-first-run', '--no-default-browser-check',
                             '--window-size=1400,900', '--disable-features=Translate'], creationflags=NO_WINDOW)


def window_open():
    """应用窗口还开着没有：浏览器开着时会独占配置文件夹里的 lockfile（Edge 启动时常常换一个进程，跟踪进程不准）"""
    lock = os.path.join(APP, 'data', 'desktop-browser', 'lockfile')
    if not os.path.exists(lock):
        return False
    try:
        open(lock, 'a').close()
        return False
    except PermissionError:
        return True
    except OSError:
        return True


def ask_room():
    """用 Windows 自带的输入框问直播间号（只能填数字）；点取消返回 0"""
    if sys.platform != 'win32':
        return int(input('直播间号：').strip() or 0)
    ps = ("Add-Type -AssemblyName Microsoft.VisualBasic;"
          "[Microsoft.VisualBasic.Interaction]::InputBox('第一次使用，请输入你的 B 站直播间号（直播间网址 live.bilibili.com/ 后面那串数字）', '雾幕', '')")
    for _ in range(3):
        r = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, creationflags=NO_WINDOW)
        text = r.stdout.decode('utf-8', 'replace').strip() if r.stdout else ''
        if not text:
            text = r.stdout.decode('gbk', 'replace').strip() if r.stdout else ''
        if not text:
            return 0
        if text.isdigit():
            return int(text)
        message('只能填数字，再输一次')
    return 0


def make_shortcut():
    """桌面上建「雾幕」快捷方式：双击就是软件窗口，没有黑窗口，图标是雾幕的"""
    if sys.platform != 'win32':
        return False
    pyw = os.path.join(os.path.dirname(python_exe()), 'pythonw.exe')
    icon = os.path.join(APP, 'static', 'art', 'icon.ico')
    try:  # 换过看板娘就用换的（2026-11-26）
        mine = sorted(n for n in os.listdir(os.path.join(APP, 'data', 'mascot')) if n.startswith('mascot-') and n.endswith('.ico'))
        if mine:
            icon = os.path.join(APP, 'data', 'mascot', mine[-1])
    except OSError:
        pass
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\\雾幕.lnk');"
          f"$s.TargetPath='{pyw}';$s.Arguments='\"{os.path.join(APP, 'desktop.py')}\"';$s.WorkingDirectory='{APP}';"
          f"$s.IconLocation='{icon}';$s.Description='雾幕';$s.Save()")
    r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], creationflags=NO_WINDOW)
    return r.returncode == 0


def main():
    args = sys.argv[1:]
    if '--shortcut' in args:
        ok = make_shortcut()
        message('桌面上已经有「雾幕」了，以后双击它打开' if ok else '快捷方式没建成，可以直接双击 start.bat')
        return
    c = config()
    if not os.path.exists(os.path.join(APP, 'config.json')):
        # 第一次打开：不再弹框问直播间号（2026-11-26 用户：填错了找不到地方改），软件里会出一张卡片让选平台、填房间号，
        # 以后在「设置 → 直播间」里随时能换
        try:
            with open(os.path.join(APP, 'config.example.json'), encoding='utf-8') as f:
                base = json.load(f)
        except (OSError, ValueError):
            base = {}
        c = {**base, **c, 'open': c.get('open', 'app')}
        with open(os.path.join(APP, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump(c, f, ensure_ascii=False, indent=2)
    port = int(c.get('port') or 8373)
    web = '--web' in args or c.get('open') == 'web'
    url = f'http://127.0.0.1:{port}/'
    if port_open(port):  # 已经开着一份：直接再开一个窗口
        if web:
            import webbrowser
            webbrowser.open(url)
        else:
            open_window(url)
        return
    updates.apply(APP, say)  # 上次下载好、还没换上的新版本，先换上
    new_bat = os.path.join(APP, 'start.bat.new')  # 从 start.bat 更新时没能当场换掉的
    if os.path.isfile(new_bat):
        try:
            os.replace(new_bat, os.path.join(APP, 'start.bat'))
        except OSError:
            pass
    server = start_server(port)
    if not wait_ready(port, server):
        message('雾幕没启动起来，看看 data\\server.log 里写了什么（或者双击 start.bat 看报错）')
        server.kill()
        return
    win = None
    if web:
        import webbrowser
        webbrowser.open(url)
    else:
        win = open_window(url)
        for _ in range(100):  # 等窗口真的开起来
            if window_open():
                break
            time.sleep(0.2)
    while True:
        code = server.poll()
        if code is not None:
            if code == updates.RESTART_CODE:  # 页面上点了「重启生效」
                v = updates.apply(APP, say)
                say(f'重启{"，换成 v" + v if v else ""}')
                server = start_server(port)
                wait_ready(port, server)
                continue
            say(f'服务停了（{code}），过 3 秒重开')
            time.sleep(3)
            server = start_server(port)
            continue
        if win is not None and not window_open():  # 窗口关了：一起停
            say('窗口关了，雾幕也停了')
            try:  # 先让它把这一场存好再退
                urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}/api/launcher/quit?t={TOKEN}', data=b'', method='POST'), timeout=5)
                server.wait(10)
            except (OSError, subprocess.TimeoutExpired):
                server.kill()
            return
        time.sleep(1)


if __name__ == '__main__':
    main()
