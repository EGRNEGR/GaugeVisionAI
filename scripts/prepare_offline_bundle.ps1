# GaugeVision AI — подготовка автономного offline wheelhouse для закрытого контура (air-gapped)
# Запускается ОДИН РАЗ на машине с доступом к PyPI (или внутреннему зеркалу).
# Пример:
#   powershell -ExecutionPolicy Bypass -File scripts/prepare_offline_bundle.ps1 -PythonExe C:\C1\GaugeVS\.venv\Scripts\python.exe

param(
    [string]$PythonExe = "python",
    [string]$WheelDir = "wheels",
    [string]$RequirementsFile = "requirements.lock"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TargetWheels = Join-Path $RepoRoot $WheelDir
$ReqPath = Join-Path $RepoRoot $RequirementsFile

if (-not (Test-Path $ReqPath)) {
    throw "Не найден файл зависимостей: $ReqPath"
}

New-Item -ItemType Directory -Force -Path $TargetWheels | Out-Null

Write-Host "[1/2] Загрузка wheel-пакетов из $RequirementsFile в $TargetWheels..."
& $PythonExe -m pip download --only-binary=:all: --dest $TargetWheels -r $ReqPath
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Часть пакетов отсутствует в формате binary wheel — повторяем без --only-binary..."
    & $PythonExe -m pip download --dest $TargetWheels -r $ReqPath
    if ($LASTEXITCODE -ne 0) {
        throw "pip download завершился с кодом $LASTEXITCODE"
    }
}

$Count = (Get-ChildItem -File $TargetWheels).Count
Write-Host "[2/2] Готово: сохранено $Count файлов в $TargetWheels."
Write-Host "Для переноса в изолированный контур скопируйте репозиторий вместе с каталогами wheels/ и models/."
