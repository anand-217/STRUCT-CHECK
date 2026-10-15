@echo off
REM Builds StructCheck.exe (needs Python ONLY on the build PC; the exe runs anywhere without Python)
cd /d "%~dp0backend"
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --name StructCheck --collect-submodules ezdxf --collect-submodules openpyxl --collect-all shapely --collect-submodules matplotlib structcheck_app.py
echo.
echo Done: backend\dist\StructCheck.exe
pause
