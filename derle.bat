@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo PyInstaller kuruluyor...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (echo Python bulunamadi. python.org adresinden kur, "Add to PATH" isaretle. & pause & exit /b 1)
python -m PyInstaller --onefile --windowed --name CM_Kadro_Tamamlayici cm_kadro_tamamlayici.py
if exist dist\CM_Kadro_Tamamlayici.exe (echo. & echo HAZIR: dist\CM_Kadro_Tamamlayici.exe) else (echo Derleme basarisiz)
pause
