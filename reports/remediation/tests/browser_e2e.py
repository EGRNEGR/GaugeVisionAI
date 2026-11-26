"""
Оркестратор браузерного E2E: настоящий сервер run.py --demo (HTTPS, RBAC, CPU) + Playwright.

  python reports/remediation/tests/browser_e2e.py --out reports/remediation/evidence/browser_e2e
Требуется Node.js и пакет playwright-core с установленным Chromium; путь к пакету —
переменная GV_PLAYWRIGHT_CORE или ключ "playwright_core" в .validation_tools.json.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gv_harness as H  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(H.ROOT / "reports" / "remediation" / "evidence" / "browser_e2e"))
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    tools = H.load_tools()
    env = dict(os.environ)
    if tools.get("playwright_core"):
        env["GV_PLAYWRIGHT_CORE"] = tools["playwright_core"]
    work = Path(tempfile.mkdtemp(prefix="gv_browser_e2e_"))
    server = H.GaugeServer(work / "server", extra_env={"GAUGEVISION_MODBUS_ENABLED": "1",
                                                       "GAUGEVISION_MODBUS_PORT": str(H.free_port())})
    result: dict = {}
    try:
        server.start()
        proc = subprocess.run(["node", str(Path(__file__).with_name("browser_e2e_driver.js")), server.base, str(out),
                               H.ADMIN_PASS, H.OPERATOR_PASS], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=600, env=env)
        print(proc.stdout[-3000:])
        if proc.stderr.strip():
            print("STDERR:", proc.stderr[-2000:])
        rep = json.loads((out / "browser_e2e_report.json").read_text(encoding="utf-8"))
        failures = list(rep.get("failures", []))
        docx = out / "e2e_spec.docx"
        md = out / "e2e_spec.md"
        if docx.is_file():
            with zipfile.ZipFile(docx) as zf:
                text = "".join(ET.fromstring(zf.read("word/document.xml")).itertext())
                media = [n for n in zf.namelist() if n.startswith("word/media/")]
            if "ТЗ-ПРИЁМКА-2026-11" not in text or "ФЗ-102" not in text:
                failures.append("в .docx нет номера документа или правового разграничения")
            if not media:
                failures.append("в .docx нет встроенных кадров")
            result["docx"] = {"bytes": docx.stat().st_size, "media": len(media)}
        else:
            failures.append("не скачан .docx")
        if md.is_file():
            result["md_bytes"] = md.stat().st_size
        else:
            failures.append("не скачан .md")
        result.update({"driver_rc": proc.returncode, "failures": failures, "passed": not failures and proc.returncode == 0})
    finally:
        server.stop()
        if server.log_path.is_file():
            shutil.copy2(server.log_path, out / "server.log")
    (out / "browser_e2e_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
