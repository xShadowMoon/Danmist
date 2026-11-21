@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 弹幕姬（演示数据）
echo 不连直播间，随机造弹幕看样式。网页地址：http://127.0.0.1:8375
start "" http://127.0.0.1:8375/
py -3 server.py --demo --port 8375
pause
