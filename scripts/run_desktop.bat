@echo off
setlocal
cd /d "%~dp0\\.."
py -m pip install -e . PySide6 PySide6-WebEngine || goto :failed
set PYTHONPATH=%CD%\\src
py run_desktop.py
exit /b %errorlevel%
:failed
echo Installation failed. Check the error above.
pause
exit /b 1
