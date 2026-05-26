@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
call .venv\Scripts\activate
streamlit run app.py
