# GaugeVision AI — подготовка автономного wheelhouse для закрытого контура (air-gapped)
# Запускается ОДИН РАЗ на машине с доступом к PyPI и индексу PyTorch (или к их внутренним зеркалам).
# Состав пакетов берётся из requirements.lock (полный закреплённый набор, включая YOLOv8 и PyTorch CPU).
#
# Windows x64, CPU (по умолчанию):
#   powershell -ExecutionPolicy Bypass -File scripts/prepare_offline_bundle.ps1 -PythonExe "C:\Program Files\Python312\python.exe"
# Linux-образ Docker (wheelhouse под manylinux, собирается на любой ОС):
#   powershell -ExecutionPolicy Bypass -File scripts/prepare_offline_bundle.ps1 -Platform manylinux_2_28_x86_64
# Внутреннее зеркало:
#   ... -PypiIndex https://mirror.local/pypi/simple -TorchIndex https://mirror.local/torch/cpu

param(
    [string]$PythonExe = "python",
    [string]$WheelDir = "wheels",
    [string]$RequirementsFile = "requirements.lock",
    [string]$TorchIndex = "https://download.pytorch.org/whl/cpu",
    [string]$PypiIndex = "https://pypi.org/simple",
    [string]$Platform = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TargetWheels = if ([System.IO.Path]::IsPathRooted($WheelDir)) { $WheelDir } else { Join-Path $RepoRoot $WheelDir }
$ReqPath = Join-Path $RepoRoot $RequirementsFile
if (-not (Test-Path $ReqPath)) { throw "Не найден файл зависимостей: $ReqPath" }

$PyVer = & $PythonExe -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
if ($PyVer -ne "3.12") { Write-Warning "Версии в requirements.lock проверены на Python 3.12, текущий: $PyVer" }

New-Item -ItemType Directory -Force -Path $TargetWheels | Out-Null
$PipArgs = @("-m", "pip", "download", "--only-binary=:all:", "--dest", $TargetWheels, "-r", $ReqPath,
             "--index-url", $TorchIndex, "--extra-index-url", $PypiIndex)
if ($Platform) { $PipArgs += @("--platform", $Platform, "--python-version", "3.12", "--implementation", "cp") }

Write-Host "[1/3] Загрузка wheel-пакетов из $RequirementsFile в $TargetWheels"
& $PythonExe @PipArgs
if ($LASTEXITCODE -ne 0) { throw "pip download завершился с кодом $LASTEXITCODE" }

Write-Host "[2/3] Контрольные суммы SHA-256 комплекта"
$Sums = Get-ChildItem -File $TargetWheels -Filter *.whl | Sort-Object Name | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower(), $_.Name
}
$Sums | Set-Content -Encoding utf8 (Join-Path $TargetWheels "SHA256SUMS.txt")

$Weights = Join-Path $RepoRoot "models\gauge_yolov8.pt"
if (-not (Test-Path $Weights)) { throw "Нет весов YOLOv8: $Weights — без них CV работает только на OpenCV-fallback" }
$Count = (Get-ChildItem -File $TargetWheels -Filter *.whl).Count
$SizeMb = [math]::Round(((Get-ChildItem -File $TargetWheels | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "[3/3] Готово: $Count пакетов, $SizeMb МБ. Перенесите в закрытый контур репозиторий вместе с wheels/ и models/."
