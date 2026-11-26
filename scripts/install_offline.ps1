# GaugeVision AI — автономная установка в чистом виртуальном окружении без доступа к сети
#   powershell -ExecutionPolicy Bypass -File scripts/install_offline.ps1 -BasePython "C:\Program Files\Python312\python.exe"
# Установка выполняется только из локального wheelhouse (--no-index); обращение pip к индексу
# пакетов невозможно. После установки проверяются целостность комплекта, совместимость
# зависимостей и загрузка локальных весов YOLOv8 на CPU.

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
if (-not (Test-Path $TargetWheels)) { throw "Не найден каталог offline wheelhouse: $TargetWheels" }
if (-not (Test-Path $ReqPath)) { throw "Не найден файл зависимостей: $ReqPath" }
if (-not (Test-Path (Join-Path $RepoRoot "models\gauge_yolov8.pt"))) { throw "Нет весов models\gauge_yolov8.pt" }

$SumsFile = Join-Path $TargetWheels "SHA256SUMS.txt"
if (Test-Path $SumsFile) {
    Write-Host "[0/4] Проверка контрольных сумм wheelhouse"
    foreach ($line in Get-Content $SumsFile) {
        if (-not $line.Trim()) { continue }
        $parts = $line.Trim() -split "\s+", 2
        $file = Join-Path $TargetWheels $parts[1].Trim()
        if (-not (Test-Path $file)) { throw "В wheelhouse отсутствует $($parts[1])" }
        if ((Get-FileHash -Algorithm SHA256 $file).Hash.ToLower() -ne $parts[0]) { throw "Не совпала SHA-256: $($parts[1])" }
    }
}

Write-Host "[1/4] Создание чистого виртуального окружения: $FullVenv"
& $BasePython -m venv $FullVenv
if ($LASTEXITCODE -ne 0) { throw "Не удалось создать venv ($LASTEXITCODE)" }
$VenvPy = Join-Path $FullVenv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { $VenvPy = Join-Path $FullVenv "bin/python" }

Write-Host "[2/4] Офлайн-установка (--no-index --find-links=$TargetWheels)"
$env:PIP_NO_INDEX = "1"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
& $VenvPy -m pip install --no-index --find-links $TargetWheels -r $ReqPath
if ($LASTEXITCODE -ne 0) { throw "Офлайн-установка завершилась с кодом $LASTEXITCODE" }
& $VenvPy -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check: несовместимые зависимости" }

Write-Host "[3/4] Проверка импортов и загрузки YOLOv8 на CPU"
$env:CUDA_VISIBLE_DEVICES = ""
$env:GAUGEVISION_DEVICE = "cpu"
$env:YOLO_OFFLINE = "1"
Push-Location $RepoRoot
try {
    & $VenvPy -B -c "import app.main; from app import vision; ok = vision.yolo_available(); print('YOLO', ok, vision.yolo_device()); raise SystemExit(0 if ok else 3)"
    if ($LASTEXITCODE -ne 0) { throw "YOLOv8 не загрузилась (код $LASTEXITCODE)" }
} finally { Pop-Location }

Write-Host "[4/4] Установка завершена. Запуск: $VenvPy -B run.py --demo --device cpu"
