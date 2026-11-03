@echo off
setlocal
cd /d "%~dp0\.."
py -m pip install -e . || exit /b 1
py run_ghost.py
pause
