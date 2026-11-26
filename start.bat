@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 雾幕

rem 找 Python：先用 Windows 版自带的 python\，再找电脑上装的
set "PY="
if exist "python\python.exe" set "PY=python\python.exe"
if not defined PY (where py >nul 2>nul && set "PY=py -3")
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo 没找到 Python。请下载 Releases 里带 Python 的 Windows 版，或者先装 Python 3.11 以上：
  echo https://www.python.org/downloads/
  pause
  exit /b 1
)

rem 从源码运行时，第一次自动装依赖
if not exist "python\python.exe" (
  %PY% -c "import aiohttp, brotli, pure_protobuf, yarl, qrcode" >nul 2>nul || (
    echo 第一次运行，正在安装依赖……
    %PY% -m pip install -r requirements.txt || (pause & exit /b 1)
  )
)

rem 第一次运行：不再问直播间号（2026-11-26），打开以后在软件里选平台、填房间号；以后在「设置 → 直播间」里换
if exist config.json goto mode
%PY% -X utf8 -c "import json;c=json.load(open('config.example.json',encoding='utf-8'));c['open']='app';json.dump(c,open('config.json','w',encoding='utf-8'),ensure_ascii=False,indent=2)" 2>nul
echo 第一次使用：打开以后在里面选平台、填直播间号就好（填错了在「设置 → 直播间」里改）。

:mode
rem 软件窗口（2026-11-25 桌面版）：交给 desktop.py，没有黑窗口；第一次顺便在桌面建快捷方式
%PY% -X utf8 -c "import json,sys;sys.exit(0 if json.load(open('config.json',encoding='utf-8-sig')).get('open','web')=='app' else 1)" 2>nul
if errorlevel 1 goto web
if exist "python\pythonw.exe" (
  if not exist "data\shortcut-made" (
    python\python.exe desktop.py --shortcut >nul 2>nul
    if not exist data mkdir data
    echo.> "data\shortcut-made"
  )
  start "" "python\pythonw.exe" desktop.py
  exit /b 0
)
start "" %PY% desktop.py
exit /b 0

:web
echo.
echo 雾幕启动中，关掉这个窗口就停了。网页地址：http://127.0.0.1:8373
start "" http://127.0.0.1:8373/
set BDB_LAUNCHER=1
:run
%PY% server.py
rem 页面上点了「重启生效」（软件内更新）：退出码 75，换上新版本再开
if errorlevel 75 if not errorlevel 76 (
  %PY% updates.py --apply --from-bat
  goto run
)
rem 连续连不上 B 站时它会自己退出（退出码 3）让人重开：这里直接重开
if errorlevel 3 if not errorlevel 4 goto run
pause
