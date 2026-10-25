@echo off
setlocal
cd /d "%~dp0"

set "APP_EXE=AIM.exe"
set "UPDATE_EXE=AIM.update.exe"
set "APP_PATH=%~dp0%APP_EXE%"

echo Downloading the latest AIM.exe from GitHub...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop'; try { $headers = @{ 'User-Agent' = 'AIM-Updater'; 'Accept' = 'application/vnd.github+json' }; $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/zfpirate/MyAimTrainning/releases/latest' -Headers $headers; $asset = $release.assets | Where-Object { $_.name -eq 'AIM.exe' } | Select-Object -First 1; if (-not $asset) { throw 'AIM.exe was not found in the latest release.' }; if ($asset.digest -notmatch '^sha256:([0-9a-fA-F]{64})$') { throw 'The latest release has no valid SHA-256 digest.' }; $expectedHash = $Matches[1]; Invoke-WebRequest -Uri $asset.browser_download_url -OutFile 'AIM.update.exe' -Headers @{ 'User-Agent' = 'AIM-Updater' }; if ((Get-Item 'AIM.update.exe').Length -ne [int64]$asset.size) { throw 'Downloaded file size does not match the release asset.' }; $actualHash = (Get-FileHash 'AIM.update.exe' -Algorithm SHA256).Hash; if ($actualHash -ne $expectedHash) { throw 'Downloaded file SHA-256 does not match the release asset.' } } catch { Write-Error $_; if (Test-Path 'AIM.update.exe') { Remove-Item 'AIM.update.exe' -Force }; exit 1 }"
if errorlevel 1 goto update_failed

echo Waiting for %APP_EXE% to close...
:waitclose
tasklist /FI "IMAGENAME eq %APP_EXE%" 2>NUL | find /I "%APP_EXE%" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto waitclose
)

move /Y "%UPDATE_EXE%" "%APP_EXE%" >NUL
if errorlevel 1 goto replace_failed

echo Update complete. Relaunching %APP_EXE%...
if not exist "%APP_PATH%" goto launch_failed
start "" /D "%~dp0" "%APP_PATH%"
if errorlevel 1 goto launch_failed
exit /b 0

:update_failed
echo.
echo Download or verification failed. The existing executable was not replaced.
pause
if exist "%APP_PATH%" start "" /D "%~dp0" "%APP_PATH%"
exit /b 1

:replace_failed
echo.
echo Could not replace %APP_EXE%. The existing executable was not replaced.
del /q "%UPDATE_EXE%" 2>NUL
pause
if exist "%APP_PATH%" start "" /D "%~dp0" "%APP_PATH%"
exit /b 1

:launch_failed
echo.
echo The update completed, but Windows could not start %APP_EXE%.
echo Start it manually from: %APP_PATH%
pause
exit /b 1
