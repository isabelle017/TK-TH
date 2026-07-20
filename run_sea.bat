@echo off
REM ============================================
REM TikTok 选品自动化 - 一键运行 (Windows)
REM ============================================
REM 用法:
REM   双击运行: 执行一次 SEA 选品分析
REM   配合任务计划程序: 定时自动执行
REM
REM 首次使用前请先:
REM   1. 复制 .env.example 为 .env 并填入 API Key
REM   2. pip install -r requirements.txt
REM ============================================

cd /d "%~dp0"

REM 检查 .env 是否存在
if not exist ".env" (
    echo [WARNING] .env 文件不存在！
    echo 请复制 .env.example 为 .env 并填入 API Key
    pause
    exit /b 1
)

REM 检查虚拟环境
if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo ========================================
echo  TikTok 选品分析 - SEA 区域
echo  时间: %DATE% %TIME%
echo ========================================

%PYTHON% scheduler.py --region sea --once

if %ERRORLEVEL% equ 0 (
    echo.
    echo [OK] 选品分析完成
) else (
    echo.
    echo [ERROR] 执行失败，请检查日志
    pause
)
