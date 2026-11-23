@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 弹幕姬

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

rem 第一次运行：问直播间号，写进 config.json
if exist config.json goto run
echo.
echo 第一次使用，请输入你的 B 站直播间号
echo （直播间网址 live.bilibili.com/ 后面那串数字）
%PY% -X utf8 -c "import json;c=json.load(open('config.example.json',encoding='utf-8'));c['room']=int(next(x for x in iter(lambda:input('直播间号：').strip(),None) if x.isdigit() or print('只能填数字，再输一次。')));json.dump(c,open('config.json','w',encoding='utf-8'),ensure_ascii=False,indent=2)" 2>nul || (
  echo.
  echo 没能读到直播间号。也可以把 config.example.json 复制成 config.json，自己填 room。
  pause
  exit /b 1
)
echo 已保存到 config.json，以后想换直播间就改这个文件。

:run
echo.
echo 弹幕姬启动中，关掉这个窗口就停了。网页地址：http://127.0.0.1:8373
start "" http://127.0.0.1:8373/
%PY% server.py
pause
