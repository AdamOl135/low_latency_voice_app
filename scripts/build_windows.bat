@echo off
REM ==============================================================================
REM Low-Latency Voice App — Windows 11 Build Batch Script
REM ==============================================================================
setlocal enabledelayedexpansion

cd /d "%~dp0\.."
echo ====================================================================
echo   Building Low-Latency Voice App for Windows 11 (x64)
echo ====================================================================

REM 1. Build C Native Audio Engine DLL
echo [1/3] Building Native Audio Engine DLL (voice_engine.dll)...
if not exist client\native\build mkdir client\native\build
cd client\native\build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --config Release
if errorlevel 1 (
    echo [-] Error compiling native audio engine.
    cd /d "%~dp0\.."
    exit /b 1
)
cd /d "%~dp0\.."

REM 2. Build Flutter Windows Client Executable
echo [2/3] Building Flutter Windows Client Executable...
cd client
call flutter config --enable-windows-desktop
call flutter pub get
call flutter build windows --release
if errorlevel 1 (
    echo [-] Error building Flutter Windows application.
    cd /d "%~dp0\.."
    exit /b 1
)
cd /d "%~dp0\.."

REM 3. Package Windows Release Bundle
echo [3/3] Packaging Windows Release Bundle...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1"

echo ====================================================================
echo   BUILD FINISHED
echo   Check dist\ for output zip and .exe files.
echo ====================================================================
pause
