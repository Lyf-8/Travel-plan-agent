@echo off
REM ============================================
REM AI 旅行攻略生成系统 - Windows 启动后端脚本
REM ============================================

chcp 65001 >nul
echo [1/4] 进入 backend 目录...
cd /d "%~dp0..\backend"

echo [2/4] 激活虚拟环境（若存在）...
if exist "..\.venv\Scripts\activate.bat" (
    call ..\.venv\Scripts\activate.bat
)

echo [3/4] 设置 HuggingFace 离线模式（模型已本地缓存，避免启动联网卡死）...
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1

echo [4/4] 启动 FastAPI 服务 (端口 8000)...
echo.
echo   API 文档: http://localhost:8000/docs
echo   停止服务: Ctrl + C
echo.

uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

pause
