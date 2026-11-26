@echo off
rem Double-click. Finds the GPU (CUDA/Vulkan/CPU), a model and adb, then links the phone.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-windows.ps1" %*
echo.
pause
