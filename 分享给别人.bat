@echo off
chcp 65001 >nul
title 高考志愿系统 - 公网分享
cd /d "D:\NewCode\高考志愿填报系统"

set PORT=8501
set PYEXE=D:\Anaconda\envs\pytorch_nightly\python.exe
set CFEXE=D:\cloudflared\cloudflared-windows-amd64.exe

echo ============================================================
echo   高考志愿填报系统 - 一键公网分享
echo ============================================================
echo.
echo [1/2] 正在后台启动 Streamlit (端口 %PORT%) ...
start "Streamlit-志愿系统" "%PYEXE%" -m streamlit run app.py --server.port %PORT% --server.headless true --browser.gatherUsageStats false

echo     等待服务起来 (约 6 秒) ...
timeout /t 6 /nobreak >nul

echo.
echo [2/2] 正在开启 Cloudflare 隧道 ...
echo.
echo ============================================================
echo   下面输出里 https://xxxx.trycloudflare.com 就是分享网址
echo   把它发给别人即可。本窗口关闭 = 隧道断开。
echo ============================================================
echo.
"%CFEXE%" tunnel --url http://localhost:%PORT%

echo.
echo 隧道已结束。如需重新分享，再次双击本文件即可。
pause
