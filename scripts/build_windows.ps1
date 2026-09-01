# ==============================================================================
# Low-Latency Voice App — Windows 11 Build & Packaging Script (PowerShell)
# Builds low_latency_voice_app.exe, voice_engine.dll, and packages into dist/
# ==============================================================================
[CmdletBinding()]
param (
    [switch]$SkipBackend = $false
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\.."
Set-Location $ProjectRoot

Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host "  Building Low-Latency Voice App for Windows 11 (x64)" -ForegroundColor Cyan
Write-Host "  Root: $ProjectRoot" -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan

# 1. Determine Version
$Version = (Select-String -Path "client\pubspec.yaml" -Pattern "^version:\s*(\S+)").Matches.Groups[1].Value.Split('+')[0]
if (-not $Version) { $Version = "1.0.0" }
Write-Host "[*] Application Version: v$Version" -ForegroundColor Green

# 2. Check Prerequisites
if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    Write-Error "Flutter SDK not found in PATH. Please install Flutter and ensure it is on your PATH."
}
if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    Write-Error "CMake not found in PATH. Please install CMake / Visual Studio C++ Build Tools."
}

# 3. Build Native C Audio Engine DLL (voice_engine.dll)
Write-Host "`n[1/4] Building Native C Audio Engine (voice_engine.dll)..." -ForegroundColor Yellow
$NativeBuildDir = "$ProjectRoot\client\native\build"
if (Test-Path $NativeBuildDir) { Remove-Item -Recurse -Force $NativeBuildDir }
New-Item -ItemType Directory -Force -Path $NativeBuildDir | Out-Null

Push-Location $NativeBuildDir
try {
    cmake .. -DCMAKE_BUILD_TYPE=Release
    cmake --build . --config Release
} finally {
    Pop-Location
}

# 4. Build Flutter Windows Client (.exe)
Write-Host "`n[2/4] Building Flutter Windows Client Release..." -ForegroundColor Yellow
Push-Location "$ProjectRoot\client"
try {
    flutter config --enable-windows-desktop
    flutter pub get
    flutter build windows --release
} finally {
    Pop-Location
}

# 5. Optional Backend Windows Build
if (-not $SkipBackend -and (Get-Command go -ErrorAction SilentlyContinue)) {
    Write-Host "`n[3/4] Compiling Go Backend for Windows (server.exe)..." -ForegroundColor Yellow
    Push-Location "$ProjectRoot\backend"
    try {
        $env:GOOS = "windows"
        $env:GOARCH = "amd64"
        go build -ldflags="-s -w" -o "$ProjectRoot\backend\server.exe" ./cmd/server
    } finally {
        Pop-Location
    }
} else {
    Write-Host "`n[3/4] Skipping Go backend build (or Go not installed)." -ForegroundColor DarkGray
}

# 6. Package Distribution
Write-Host "`n[4/4] Packaging Windows 11 Release ZIP..." -ForegroundColor Yellow
$DistDir = "$ProjectRoot\dist"
if (-not (Test-Path $DistDir)) { New-Item -ItemType Directory -Force -Path $DistDir | Out-Null }

$ClientDist = "$DistDir\low_latency_voice_app-v$Version-windows-x64"
if (Test-Path $ClientDist) { Remove-Item -Recurse -Force $ClientDist }
New-Item -ItemType Directory -Force -Path $ClientDist | Out-Null

# Copy Flutter Windows Release Bundle
Copy-Item -Recurse -Force "$ProjectRoot\client\build\windows\x64\runner\Release\*" "$ClientDist\"

# Copy voice_engine.dll
if (Test-Path "$NativeBuildDir\Release\voice_engine.dll") {
    Copy-Item -Force "$NativeBuildDir\Release\voice_engine.dll" "$ClientDist\"
} elseif (Test-Path "$NativeBuildDir\voice_engine.dll") {
    Copy-Item -Force "$NativeBuildDir\voice_engine.dll" "$ClientDist\"
}

@"
Low-Latency Voice & Text Desktop Client
Version: v$Version
Platform: Windows 10 / Windows 11 (x64)

Usage:
  Double-click 'low_latency_voice_app.exe' to launch the client.

Network Settings:
  WebSocket Control Plane: ws://<SERVER_IP>:8085/ws
  UDP Voice SFU Stream:   <SERVER_IP>:7878/udp
"@ | Out-File -FilePath "$ClientDist\README.txt" -Encoding utf8

$ZipPath = "$DistDir\low_latency_voice_app-v$Version-windows-x64.zip"
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path "$ClientDist\*" -DestinationPath $ZipPath -Force

Write-Host "`n====================================================================" -ForegroundColor Green
Write-Host "  WINDOWS 11 BUILD COMPLETE!" -ForegroundColor Green
Write-Host "  Executable: $ClientDist\low_latency_voice_app.exe" -ForegroundColor Green
Write-Host "  Zip Bundle: $ZipPath" -ForegroundColor Green
Write-Host "====================================================================" -ForegroundColor Green
