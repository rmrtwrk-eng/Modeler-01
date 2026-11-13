@echo off
REM Builds dist\ShipStab.exe  (run on Windows, Python 3.10+ installed and on PATH)
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install numpy scipy ezdxf pyinstaller || goto :err
pyinstaller --noconfirm --onefile --windowed --name ShipStab ^
  --collect-submodules scipy.interpolate --collect-all ezdxf shipstab_app.py || goto :err
echo.
echo Done: dist\ShipStab.exe
pause
exit /b 0
:err
echo BUILD FAILED
pause
exit /b 1
