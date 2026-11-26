"""
Оркестратор полного 25-шагового аутентифицированного Browser E2E (CPU-only, Air-Gapped).
Запускает реальный сервер `run.py --demo --no-https --device cpu` с включённым RBAC,
выполняет `remediation_browser_driver.js` через Playwright, проверяет OpenXML скачанного .docx
и корректно останавливает сервер.
"""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(r"C:\Hakatons\GaugeVisionAIDesign DashBoard")
SCRATCH = Path(__file__).resolve().parent
OUT_DIR = Path(os.environ.get("REM_E2E_OUT", str(SCRATCH / "remediation_e2e_out")))
OUT_DIR.mkdir(parents=True, exist_ok=True)
DRIVER = SCRATCH / "remediation_browser_driver.js"

PORT = 18450
BASE_URL = f"https://127.0.0.1:{PORT}"
TMP_DIR = Path(tempfile.mkdtemp(prefix="gv_rem_e2e_"))


def wait_server(url: str, timeout: float = 25.0) -> None:
    ctx = ssl._create_unverified_context()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/meta", context=ctx, timeout=2.0) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"Сервер не поднялся за {timeout}с на {url}")


def main() -> None:
    env = os.environ.copy()
    env.update({
        "CUDA_VISIBLE_DEVICES": "",
        "GAUGEVISION_DEVICE": "cpu",
        "GAUGEVISION_DEMO": "1",
        "GAUGEVISION_AUTH_REQUIRED": "1",
        "GAUGEVISION_MODBUS_ENABLED": "1",
        "GAUGEVISION_MODBUS_PORT": "15540",
        "GAUGEVISION_DB": str(TMP_DIR / "e2e.db"),
        "GAUGEVISION_SF_DB": str(TMP_DIR / "e2e_sf.db"),
        "GAUGEVISION_INCIDENTS_DIR": str(TMP_DIR / "incidents"),
        "GAUGEVISION_AUTO_SPECS_DIR": str(TMP_DIR / "auto_specs"),
        "YOLO_CONFIG_DIR": str(TMP_DIR / "yolo_cfg"),
    })
    log_path = OUT_DIR / "e2e_server.log"
    log_f = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-B", str(ROOT / "run.py"), "--demo", "--host", "127.0.0.1", "--port", str(PORT), "--device", "cpu"],
        cwd=str(ROOT),
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_server(BASE_URL, timeout=30.0)
        res = subprocess.run(
            ["node", str(DRIVER), BASE_URL, str(OUT_DIR), "GaugeAdmin!2026"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        print(res.stdout)
        if res.stderr:
            print("STDERR:", res.stderr)
        if res.returncode != 0:
            raise SystemExit(res.returncode)

        # Проверка скачанного .docx (OpenXML + встроенные JPEG + ФЗ-102 дисклеймер)
        docx_path = OUT_DIR / "remediation_e2e_spec.docx"
        md_path = OUT_DIR / "remediation_e2e_spec.md"
        assert docx_path.exists() and docx_path.stat().st_size > 15_000
        assert md_path.exists() and "ФЗ-102" in md_path.read_text(encoding="utf-8")
        with zipfile.ZipFile(docx_path, "r") as zf:
            names = set(zf.namelist())
            xml_txt = "".join(ET.fromstring(zf.read("word/document.xml")).itertext())
            assert "ТЗ-РЕМЕДИАЦИЯ-2026-01" in xml_txt
            assert "ФЗ-102" in xml_txt
            imgs = [n for n in names if n.startswith("word/media/image")]
            assert len(imgs) >= 1, f"Нет встроенных кадров в .docx: {names}"

        rep = json.loads((OUT_DIR / "remediation_browser_report.json").read_text(encoding="utf-8"))
        diag = rep["diagnostics"]
        assert diag["externalNetworkRequestsBlocked"] == 0, f"Утечка во внешнюю сеть: {diag}"
        assert len(diag["consoleErrors"]) == 0, f"Console errors: {diag['consoleErrors']}"
        assert len(diag["pageErrors"]) == 0, f"Page errors: {diag['pageErrors']}"
        assert len(diag["failedRequests"]) == 0, f"Failed requests: {diag['failedRequests']}"
        for vp in ("1920x1080", "1440x900", "1280x720"):
            assert rep["viewports"][vp]["clipped"] is False, f"Обрезка на {vp}: {rep['viewports'][vp]}"
            assert rep["viewports"][vp]["middleDotCount"] == 0, f"Средняя точка на {vp}"
        assert rep["steps"]["step25_logoutReopenedModal"] is True
        print("AUTHENTICATED 25-STEP E2E PASSED 100%")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_f.close()


if __name__ == "__main__":
    main()
