"""
Подготовка сторонних инструментов стендовой валидации (вне окружения приложения).

  python setup_validation_tools.py --dir <каталог_инструментов>

Создаёт отдельное venv с amqtt (MQTT-брокер и клиент) и pymodbus (клиент Modbus TCP),
скачивает mediamtx (RTSP-сервер) и ffmpeg (издатель RTSP) с GitHub Releases и
записывает пути в tests/.validation_tools.json (файл в .gitignore не нужен: путь
локальный, но секретов не содержит). Инструменты нужны только для испытаний
интеграции и soak; приложение их не использует.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

MEDIAMTX_URL = "https://github.com/bluenviron/mediamtx/releases/download/v1.21.4/mediamtx_v1.21.4_windows_amd64.zip"
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"


def fetch(url: str, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.is_file():
        print("download", url)
        urllib.request.urlretrieve(url, dst)
    return dst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="каталог инструментов (вне репозитория)")
    ap.add_argument("--python", default=sys.executable, help="интерпретатор Python 3.10+ для venv инструментов")
    args = ap.parse_args()
    base = Path(args.dir).resolve()
    venv = base / "venv"
    if not venv.is_dir():
        subprocess.run([args.python, "-m", "venv", str(venv)], check=True)
    py = venv / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")
    subprocess.run([str(py), "-m", "pip", "install", "-q", "amqtt==0.12.2", "pymodbus==3.16.2"], check=True)

    mtx_zip = fetch(MEDIAMTX_URL, base / "dl" / "mediamtx.zip")
    with zipfile.ZipFile(mtx_zip) as zf:
        zf.extractall(base / "mediamtx")
    ff_zip = fetch(FFMPEG_URL, base / "dl" / "ffmpeg.zip")
    with zipfile.ZipFile(ff_zip) as zf:
        zf.extractall(base / "ffmpeg")
    ffmpeg = next((base / "ffmpeg").rglob("ffmpeg.exe"))
    scripts = py.parent
    tools = {
        "tools_py": str(py),
        "amqtt": str(scripts / ("amqtt.exe" if sys.platform.startswith("win") else "amqtt")),
        "mediamtx": str(base / "mediamtx" / "mediamtx.exe"),
        "ffmpeg": str(ffmpeg),
    }
    out = Path(__file__).resolve().parent / ".validation_tools.json"
    out.write_text(json.dumps(tools, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(tools, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
