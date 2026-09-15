@echo off
REM ============================================
REM AI 旅行攻略生成系统 - Windows 启动前端脚本
REM ============================================

chcp 65001 >nul
echo [1/3] 进入 frontend 目录...
cd /d "%~dp0..\frontend"

echo [2/3] 检查依赖（首次运行会自动 npm install）...
if not exist "node_modules" (
    echo   node_modules 不存在，开始安装依赖...
    call npm install
)

echo [3/3] 启动 Vite 开发服务 (端口 5173)...
echo.
echo   前端地址: http://localhost:5173
echo   停止服务: Ctrl + C
echo.

call npm run dev

pause
