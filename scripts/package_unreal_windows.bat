@echo off
setlocal
set "REPO=%~dp0.."
if "%UE_ENGINE_DIR%"=="" set "UE_ENGINE_DIR=C:\Program Files\Epic Games\UE_5.4"
set "PROJECT=%REPO%\unreal\VericutViewer\VericutViewer.uproject"
set "OUTPUT=%REPO%\dist\windows"

if exist "%REPO%\venv\Scripts\python.exe" (
  set "PYTHON=%REPO%\venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)

"%PYTHON%" -B -m app.main --file "%REPO%\examples\simple_pocket.nc" --unreal-export "%REPO%\unreal\VericutViewer\Content\Data\vericut_scene.json"
if errorlevel 1 exit /b %errorlevel%

call "%UE_ENGINE_DIR%\Engine\Build\BatchFiles\RunUAT.bat" BuildCookRun -project="%PROJECT%" -noP4 -platform=Win64 -clientconfig=Shipping -build -cook -stage -pak -archive -archivedirectory="%OUTPUT%" -prereqs
if errorlevel 1 exit /b %errorlevel%
if exist "%OUTPUT%\VericutViewer-Windows-portable.zip" del "%OUTPUT%\VericutViewer-Windows-portable.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%OUTPUT%\Windows\*' -DestinationPath '%OUTPUT%\VericutViewer-Windows-portable.zip' -CompressionLevel Optimal"
if errorlevel 1 exit /b %errorlevel%
echo Windows package: %OUTPUT%\Windows\VericutViewer.exe
echo Portable ZIP: %OUTPUT%\VericutViewer-Windows-portable.zip
