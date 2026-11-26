@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM Безопасный запуск на ноутбуке: инференс строго на CPU (без нагрузки на дискретную GPU)
set "CUDA_VISIBLE_DEVICES="
set "GAUGEVISION_DEVICE=cpu"
set "GAUGEVISION_DEMO=1"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py --demo --device cpu %*
) else if exist "C:\C1\GaugeVS\.venv\Scripts\python.exe" (
    "C:\C1\GaugeVS\.venv\Scripts\python.exe" run.py --demo --device cpu %*
) else (
    py -3.12 run.py --demo --device cpu %*
)
