"""换看板娘以后，桌面和开始菜单上「雾幕」快捷方式的图标也跟着换（2026-11-26，Gemini 反馈）。

Windows Vista 以后 .ico 里可以直接装 PNG，所以不用别的库：把 32 / 64 / 192 / 256 这几张 PNG 原样封进一个 .ico。
图标文件名每次带上版本号（mascot-<版本>.ico），资源管理器按路径缓存图标，换了名字才会马上刷新。"""
import os
import struct
import subprocess
import sys

NO_WINDOW = 0x08000000


def png_size(data):
    """PNG 文件头里写着宽高"""
    if not data.startswith(b'\x89PNG\r\n\x1a\n') or data[12:16] != b'IHDR':
        raise ValueError('不是 PNG')
    return struct.unpack('>II', data[16:24])


def make_ico(pngs):
    """pngs：几张 PNG 的内容。超过 256 的不放（.ico 最大 256）"""
    items = []
    for data in pngs:
        w, h = png_size(data)
        if w <= 256 and h <= 256:
            items.append((w, h, data))
    if not items:
        raise ValueError('没有能用的尺寸')
    items.sort(key=lambda x: x[0])
    head = struct.pack('<HHH', 0, 1, len(items))
    offset = 6 + 16 * len(items)
    entries, body = b'', b''
    for w, h, data in items:
        entries += struct.pack('<BBBBHHII', w % 256, h % 256, 0, 0, 1, 32, len(data), offset + len(body))
        body += data
    return head + entries + body


def write_ico(folder, sizes, ver):
    """用文件夹里的 icon-<尺寸>.png 拼一个 mascot-<ver>.ico，旧的删掉。返回新文件的路径"""
    pngs = []
    for n in sizes:
        try:
            with open(os.path.join(folder, f'icon-{n}.png'), 'rb') as f:
                pngs.append(f.read())
        except OSError:
            pass
    data = make_ico(pngs)
    path = os.path.join(folder, f'mascot-{ver}.ico')
    with open(path + '.tmp', 'wb') as f:
        f.write(data)
    os.replace(path + '.tmp', path)
    remove_old(folder, keep=path)
    return path


def remove_old(folder, keep=''):
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        p = os.path.join(folder, name)
        if name.startswith('mascot-') and name.endswith('.ico') and p != keep:
            try:
                os.remove(p)
            except OSError:
                pass


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def update_shortcuts(app_dir, icon):
    """桌面和开始菜单里的「雾幕.lnk」，只改指向这份雾幕的（工作目录是 app_dir 的），别的不碰。返回改了几个"""
    if sys.platform != 'win32':
        return 0
    ps = ("$n=0;$sh=New-Object -ComObject WScript.Shell;"
          "foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){"
          "$p=Join-Path $d '雾幕.lnk';if(Test-Path -LiteralPath $p){$s=$sh.CreateShortcut($p);"
          f"if($s.WorkingDirectory.TrimEnd('\\') -ieq {ps_quote(os.path.normpath(app_dir))}){{$s.IconLocation={ps_quote(icon)};$s.Save();$n++}}}}}};"
          "try{ie4uinit.exe -show}catch{};$n")
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], capture_output=True,
                           text=True, timeout=30, creationflags=NO_WINDOW)
        return int((r.stdout or '0').strip().splitlines()[-1] or 0)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return 0
