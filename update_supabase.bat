@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe scripts\update_supabase.py --max-pages 300
) else (
    python scripts\update_supabase.py --max-pages 300
)
pause
