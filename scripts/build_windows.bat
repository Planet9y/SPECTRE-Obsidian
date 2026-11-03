@echo off
setlocal
cd /d "%~dp0\\.."
echo [1/3] Installing desktop dependencies...
py -m pip install -e ".[dev]" PySide6 PySide6-WebEngine || goto :failed
echo [2/3] Running automated tests...
py -m pytest -q || goto :failed
echo [3/3] Building native-window SPECTRE...
py -m PyInstaller --noconfirm --clean --onefile --windowed --name SPECTRE --icon assets\\spectre.ico --add-data "web;web" --add-data "assets\\spectre.ico;assets" --collect-all PySide6.QtWebEngineCore --collect-all PySide6.QtWebEngineWidgets --paths src run_desktop.py || goto :failed
echo.
echo DONE: dist\\SPECTRE.exe
echo This executable opens its own desktop window, not your web browser.
pause
exit /b 0
:failed
echo.
echo Build failed. Review the error messages above.
pause
exit /b 1
