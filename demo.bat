@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 雾幕（演示数据）

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
if not exist "python\python.exe" (
  %PY% -c "import aiohttp, brotli, pure_protobuf, yarl, qrcode" >nul 2>nul || (
    echo 第一次运行，正在安装依赖……
    %PY% -m pip install -r requirements.txt || (pause & exit /b 1)
  )
)

echo 不连直播间，随机造弹幕看样式。网页地址：http://127.0.0.1:8375
start "" http://127.0.0.1:8375/
%PY% server.py --demo --port 8375
pause
