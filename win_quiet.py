"""叫音乐客户端放歌时，把它弹出来的窗口压回去（2026-11-28 用户实测：网易云换歌会弹窗口，游戏没被切出去但被挡住）。

做法：叫客户端之前记下它现在有哪些窗口是显示着的、前台是谁；之后几秒里，客户端新冒出来的窗口
马上最小化（不抢焦点），要是前台被它抢走了，再把原来的前台窗口（比如游戏）还回去。
只动这个客户端自己的窗口，本来就开着在看的不动。只有 Windows 有用，别的系统什么都不做。
"""
import ctypes
import os
import sys
import threading
import time

SW_SHOWMINNOACTIVE = 7


def _api():
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u32.IsWindowVisible.argtypes = [wintypes.HWND]
    u32.IsIconic.argtypes = [wintypes.HWND]
    u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.SetForegroundWindow.argtypes = [wintypes.HWND]
    u32.IsWindow.argtypes = [wintypes.HWND]
    u32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    u32.GetWindow.restype = wintypes.HWND
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    return u32, k32, wintypes


def _exe_of(hwnd, u32, k32, wintypes, cache):
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value in cache:
        return cache[pid.value]
    name = ''
    h = k32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        buf = ctypes.create_unicode_buffer(520)
        n = wintypes.DWORD(520)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            name = os.path.basename(buf.value).lower()
        k32.CloseHandle(h)
    cache[pid.value] = name
    return name


def _shown_windows(exes, u32, k32, wintypes):
    """这个客户端现在显示着（没最小化）的顶层窗口"""
    found, cache = set(), {}
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        try:
            if u32.IsWindowVisible(hwnd) and not u32.IsIconic(hwnd) and not u32.GetWindow(hwnd, 4) \
                    and _exe_of(hwnd, u32, k32, wintypes, cache) in exes:  # GW_OWNER：只看主窗口
                found.add(int(hwnd))
        except Exception:
            pass
        return True
    u32.EnumWindows(proc(cb), 0)
    return found


def keep_quiet(launch, exes, seconds=6.0):
    """launch() 叫客户端放歌；之后 seconds 秒里，客户端新弹出来的窗口压回去。返回 launch() 的结果"""
    if sys.platform != 'win32':
        return launch()
    try:
        u32, k32, wintypes = _api()
        exes = {e.lower() for e in exes}
        before = _shown_windows(exes, u32, k32, wintypes)
        fg = u32.GetForegroundWindow()
        fg_is_client = bool(fg) and _exe_of(fg, u32, k32, wintypes, {}) in exes  # 主播本来就在看客户端：不压
    except Exception:
        return launch()
    out = launch()
    if fg_is_client:
        return out

    def watch():
        end = time.time() + seconds
        while time.time() < end:
            try:
                for h in _shown_windows(exes, u32, k32, wintypes) - before:
                    u32.ShowWindow(h, SW_SHOWMINNOACTIVE)
                now = u32.GetForegroundWindow()
                if fg and now and now != fg and u32.IsWindow(fg) and _exe_of(now, u32, k32, wintypes, {}) in exes:
                    u32.SetForegroundWindow(fg)  # 前台被客户端抢了：还给原来的（游戏）
            except Exception:
                pass
            time.sleep(0.05)
    threading.Thread(target=watch, daemon=True).start()
    return out
