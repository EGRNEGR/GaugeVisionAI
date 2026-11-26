# GaugeVision AI — автономная установка в чистом виртуальном окружении без интернета
# Пример:
#   powershell -ExecutionPolicy Bypass -File scripts/install_offline.ps1 -VenvDir .venv_offline

param(
    [string]$BasePython = "python",
    [string]$VenvDir = ".venv_offline",
    [string]$WheelDir = "wheels",
    [string]$RequirementsFile = "requirements.lock"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FullVenv = if ([System.IO.Path]::IsPathRooted($VenvDir)) { $VenvDir } else { Join-Path $RepoRoot $VenvDir }
$TargetWheels = if ([System.IO.Path]::IsPathRooted($WheelDir)) { $WheelDir } else { Join-Path $RepoRoot $WheelDir }
$ReqPath = Join-Path $RepoRoot $RequirementsFile

if (-not (Test-Path $TargetWheels)) {
    throw "Не найден каталог offline wheelhouse: $TargetWheels"
}
if (-not (Test-Path $ReqPath)) {
    throw "Не найден файл зависимостей: $ReqPath"
}

Write-Host "[1/3] Создание чистого виртуального окружения: $FullVenv"
& $BasePython -m venv $FullVenv
if ($LASTEXITCODE -ne 0) { throw "Не удалось создать venv ($LASTEXITCODE)" }

$VenvPy = Join-Path $FullVenv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    $VenvPy = Join-Path $FullVenv "bin/python"
}

Write-Host "[2/3] Офлайн-установка зависимостей (--no-index --find-links=$TargetWheels)..."
& $VenvPy -m pip install --no-index --find-links $TargetWheels -r $ReqPath
if ($LASTEXITCODE -ne 0) { throw "Офлайн-установка завершилась с кодом $LASTEXITCODE" }

Write-Host "[3/3] Проверка импортов и автономного запуска модулей (CPU-only)..."
$env:CUDA_VISIBLE_DEVICES = ""
$env:GAUGEVISION_DEVICE = "cpu"
& $VenvPy -B -c "import fastapi, uvicorn, httpx, websockets, cv2, numpy, PIL, aiosqlite, cryptography, qrcode; import app.main, app.scada_gateway, app.store_forward, app.dispatch_analyzer, app.spec_generator, app.auth; print('OFFLINE_INSTALL_OK')"
if ($LASTEXITCODE -ne 0) { throw "Проверка импортов не прошла ($LASTEXITCODE)" }

Write-Host "Установка завершена успешно. Запуск: $VenvPy -B run.py --demo --device cpu"
