@echo off
chcp 65001 >nul
title 文生视频 - 注册 Windows 服务 (NSSM)
echo ========================================
echo  注册文生视频为 Windows 服务
echo ========================================
echo.
echo 需要先下载 NSSM: https://nssm.cc/download
echo 将 nssm.exe 放到本目录下，或添加到 PATH
echo.

:: ── 检查 nssm ──
where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 找不到 nssm.exe
    echo 请从 https://nssm.cc/download 下载，放到 deploy\ 目录
    pause
    exit /b 1
)

:: ── 安装服务 ──
set "ROOT=%~dp0.."
set "PYTHON=python"
set "UVICORN=%PYTHON% -m uvicorn server:app --host 127.0.0.1 --port 8000"

echo [1/2] 注册 API 服务...
nssm install text2video-server "%PYTHON%" "-m uvicorn server:app --host 127.0.0.1 --port 8000"
nssm set text2video-server AppDirectory "%ROOT%"
nssm set text2video-server DisplayName "文生视频 API 服务"
nssm set text2video-server Description "FastAPI 视频生成 API"
nssm set text2video-server Start SERVICE_AUTO_START
nssm set text2video-server AppStdout "%ROOT%\_server_data\logs\server.log"
nssm set text2video-server AppStderr "%ROOT%\_server_data\logs\server.err"
nssm set text2video-server AppRotateFiles 1
nssm set text2video-server AppRotateSeconds 86400

echo [2/2] 注册 Worker 服务...
nssm install text2video-worker "%PYTHON%" "worker.py"
nssm set text2video-worker AppDirectory "%ROOT%"
nssm set text2video-worker DisplayName "文生视频 Worker"
nssm set text2video-worker Description "视频渲染 Worker 进程"
nssm set text2video-worker Start SERVICE_AUTO_START
nssm set text2video-worker AppStdout "%ROOT%\_server_data\logs\worker.log"
nssm set text2video-worker AppStderr "%ROOT%\_server_data\logs\worker.err"
nssm set text2video-worker AppRotateFiles 1
nssm set text2video-worker AppRotateSeconds 86400

echo.
echo 服务注册完成！执行以下命令启动:
echo   net start text2video-server
echo   net start text2video-worker
echo.
echo 管理服务: services.msc
echo 停止服务: net stop text2video-server / net stop text2video-worker
echo 卸载服务: nssm remove text2video-server / nssm remove text2video-worker
echo.
pause
