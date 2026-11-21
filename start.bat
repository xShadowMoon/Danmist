@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 弹幕姬
echo 弹幕姬启动中，关掉这个窗口就停了。网页地址：http://127.0.0.1:8373
start "" http://127.0.0.1:8373/
py -3 server.py
pause
