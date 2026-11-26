"""
Повторный прогон неизменённых аудиторских скриптов Gemini (reports/audit/tests/audit_01…05)
на финальном коде, строго CPU. Скрипты не модифицируются; отличия условий запуска фиксируются:
  • audit_02 запускается дважды: штатно (MQTT QoS 1) и с GAUGEVISION_MQTT_QOS=0 — встроенный
    в скрипт эмулятор брокера не отправляет PUBACK, поэтому при QoS 1 его MQTT-блок не может
    подтвердить доставку (настоящий QoS 1 проверен на брокере amqtt в interop_rtsp_mqtt_modbus.py);
  • audit_04 запускается с GAUGEVISION_AUTH_REQUIRED=0: скрипт написан до внедрения RBAC и не
    выполняет вход (аутентифицированный браузерный сценарий — browser_e2e.py).

  python reports/remediation/tests/rerun_original_audits.py --out reports/remediation/evidence/original_audit_rerun
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AUDIT = ROOT / "reports" / "audit" / "tests"

RUNS = [
    ("audit_01_cv_regression", "audit_01_cv_regression.py", {}),
    ("audit_02_qos1_default", "audit_02_track2_streams_sf_scada.py", {}),
    ("audit_02_qos0_emulator_compat", "audit_02_track2_streams_sf_scada.py", {"GAUGEVISION_MQTT_QOS": "0"}),
    ("audit_03_security_rbac_on", "audit_03_track1_dispatch_specs_security.py", {}),
    ("audit_04_hmi_auth_off_compat", "audit_04_hmi_browser_airgap_e2e.py", {"GAUGEVISION_AUTH_REQUIRED": "0"}),
    ("audit_05_soak_edge_cases", "audit_05_soak_and_edge_cases.py", {}),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "reports" / "remediation" / "evidence" / "original_audit_rerun"))
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    base_out = Path(args.out)
    base_out.mkdir(parents=True, exist_ok=True)
    summary = []
    for name, script, extra in RUNS:
        if args.only and args.only not in name:
            continue
        out = base_out / name
        out.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GAUGEVISION_")}
        env.update({"CUDA_VISIBLE_DEVICES": "", "GAUGEVISION_DEVICE": "cpu", "AUDIT_OUT_DIR": str(out),
                    "PYTHONIOENCODING": "utf-8", **extra})
        t0 = time.time()
        proc = subprocess.run([sys.executable, "-B", str(AUDIT / script)], cwd=str(ROOT), env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
        (out / "stdout.txt").write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr[-20000:], encoding="utf-8")
        rec = {"run": name, "script": script, "env_overrides": extra, "exit_code": proc.returncode,
               "seconds": round(time.time() - t0, 1),
               "outputs": sorted(p.name for p in out.iterdir() if p.name != "stdout.txt")}
        summary.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    (base_out / "rerun_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
