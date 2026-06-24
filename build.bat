@echo off
cd /d "%~dp0"
echo === Midea PortaSplit Preis-Monitor - Build ===
echo.

:: Install dependencies
echo [1/3] Installiere Abhaengigkeiten ...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo FEHLER: pip install fehlgeschlagen
    pause
    exit /b 1
)

:: Clean old build
echo [2/3] Raeume altes Build ...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

:: Build .exe
::  - --collect-all playwright  bundles Playwright's node driver so the browser
::    scrapers work in the frozen exe.
::  - No Chromium is bundled: at runtime the app uses an installed browser
::    (Playwright Chromium if present, otherwise Microsoft Edge / Chrome).
echo [3/3] Baue .exe (PyInstaller) ...
pyinstaller --noconfirm --onefile --windowed ^
    --name "MideaPortaSplitMonitor" ^
    --add-data "config.json;." ^
    --collect-all playwright ^
    main.py

if %errorlevel% neq 0 (
    echo FEHLER: PyInstaller fehlgeschlagen
    pause
    exit /b 1
)

echo.
echo === Fertig! ===
echo Die .exe liegt unter: dist\MideaPortaSplitMonitor.exe
echo Laeuft auf jedem Windows-PC: nutzt installiertes Chromium/Edge/Chrome.
echo.
pause
