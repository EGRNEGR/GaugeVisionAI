"""
Пересчёт матрицы трассируемости 75 требований (методика reports/remediation/tests/build_rtm.py)
после закрытия REQ-API-07 (стыковка GaugeVision AI с реальной SCADA Ignition 8.3.10).

Правила:
  - Исходные reports/audit/ и reports/remediation/ НЕ изменяются.
  - REQ-CV-05 НЕ затрагивается (остаётся NOT VERIFIED).
  - Балл направления = макс. балл × (PASS + 0,5 × PARTIAL) / число требований направления.
  - Результат: reports/industrial_validation/REQUIREMENTS_TRACEABILITY_MATRIX.csv
    и reports/industrial_validation/evidence/scada/score_after_scada.json.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REM_CSV = ROOT / "reports" / "remediation" / "REQUIREMENTS_TRACEABILITY_MATRIX.csv"
OUT_CSV = ROOT / "reports" / "industrial_validation" / "REQUIREMENTS_TRACEABILITY_MATRIX.csv"
SCORE_OUT = ROOT / "reports" / "industrial_validation" / "evidence" / "scada" / "score_after_scada.json"
RECON_JSON = ROOT / "reports" / "industrial_validation" / "evidence" / "scada" / "reconciliation_30min_summary.json"
SCEN_JSON = ROOT / "reports" / "industrial_validation" / "evidence" / "scada" / "scada_scenarios_results.json"

MAX_POINTS = {
    "Архитектурная видеоаналитика": 12,
    "Store-and-Forward и отказоустойчивость": 15,
    "API и промышленные интеграции": 8,
    "Аналитика и умная диспетчеризация": 15,
    "Генерация инженерной документации": 15,
    "Корректность и сохранение CV-инференса": 10,
    "Функциональность и качество HMI": 10,
    "Безопасность и автономность": 8,
    "Архитектура и качество кода": 4,
    "Тестирование и воспроизводимость": 3,
}


def main() -> None:
    rows = list(csv.DictReader(open(REM_CSV, encoding="utf-8")))
    assert len(rows) == 75, f"Expected 75 requirements, got {len(rows)}"

    recon = json.loads(RECON_JSON.read_text(encoding="utf-8"))
    scen = json.loads(SCEN_JSON.read_text(encoding="utf-8"))["scenarios"]

    # Проверяем, выполнены ли все критерии для перевода REQ-API-07 в PASS
    all_scen_ok = all(bool(v.get("ok")) for v in scen.values())
    recon_ok = (
        recon["actual_duration_s"] >= 1800.0
        and recon["instruments_checked"] == 36
        and recon["good_quality_pct"] >= 99.0
        and recon["status_match_pct"] >= 95.0
        and (recon["nan_match_pct"] is None or recon["nan_match_pct"] >= 99.0)
    )
    new_status = "PASS" if (all_scen_ok and recon_ok) else "PARTIAL"
    dur_min = round(recon["actual_duration_s"] / 60.0, 1)

    actual_text = (
        f"Подтверждён реальный обмен с SCADA Ignition 8.3.10 (Modbus Driver v2, 127.0.0.1:15020, Unit ID 1, read-only): "
        f"устройство Connected, 738 read-only тегов (36 приборов + системный блок 900–911 + расширенный блок v2 2000+idx*8), "
        f"мнемосхема Perspective «GaugeVision — пульт» (ISA-101, тренд Tag Historian). "
        f"Непрерывная сверка {dur_min} мин по всем 36 приборам ({recon['total_compared_pairs']} парных замеров, "
        f"{recon['modbus_requests_served_during_run']} запросов Modbus): Good quality {recon['good_quality_pct']} %, "
        f"совпадение статусов {recon['status_match_pct']} %, NaN/«Нет данных» {recon['nan_match_pct']} %, "
        f"ср. отн. расхождение {recon['global_mean_rel_err_pct']} %. "
        f"Проверены переходы OK/WARNING/CRITICAL/STALE, S&F 904/905, зависание heartbeat HR 906 без обрыва TCP "
        f"(детекция {scen['heartbeat_freeze_no_tcp_drop']['detect_stale_s']} с, восстановление {scen['heartbeat_freeze_no_tcp_drop']['recover_fresh_s']} с), "
        f"обрыв TCP ({scen['tcp_drop_and_auto_reconnect']['detect_link_lost_s']} с до Bad quality) и автовосстановление "
        f"({scen['tcp_drop_and_auto_reconnect']['reconnect_after_gv_ready_s']} с после старта шлюза). "
        f"Ограничения: trial-режим Ignition, локальный контур 127.0.0.1, MasterSCADA не проверялась"
    )
    ev_text = (
        "reports/industrial_validation/SCADA_INTEGRATION_REPORT.md; "
        "reports/industrial_validation/evidence/scada/; "
        "integrations/ignition/"
    )

    out_rows = []
    agg: dict[str, dict[str, int]] = {}
    for r in rows:
        row = dict(r)
        if row["ID"] == "REQ-API-07":
            row["Статус повторной приёмки"] = new_status
            row["Фактический результат повторной приёмки"] = actual_text
            row["Доказательство"] = ev_text
            row["Состояние дефектов"] = "REQ-API-07 закрыт на Ignition 8.3.10" if new_status == "PASS" else "Частично подтверждён"
        st = row["Статус повторной приёмки"]
        d = agg.setdefault(row["Направление"], {"PASS": 0, "PARTIAL": 0, "FAIL": 0, "NOT VERIFIED": 0, "n": 0})
        d[st] += 1
        d["n"] += 1
        out_rows.append(row)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    total = 0.0
    dirs = {}
    for name, mx in MAX_POINTS.items():
        d = agg[name]
        pts = mx * (d["PASS"] + 0.5 * d["PARTIAL"]) / d["n"]
        total += pts
        dirs[name] = {**d, "max": mx, "points": round(pts, 2), "points_exact": round(pts, 6)}

    counts = {k: sum(d[k] for d in agg.values()) for k in ("PASS", "PARTIAL", "FAIL", "NOT VERIFIED")}
    score = {
        "req_api_07_status": new_status,
        "req_cv_05_status": next(r["Статус повторной приёмки"] for r in out_rows if r["ID"] == "REQ-CV-05"),
        "directions": dirs,
        "total_before": 96.65,
        "total_after": round(total, 2),
        "total_exact": round(total, 6),
        "delta": round(total - 96.65, 2),
        "counts": counts,
        "compliance_pct": round((counts["PASS"] + 0.5 * counts["PARTIAL"]) / 75 * 100, 1),
        "verified_pct": round((75 - counts["NOT VERIFIED"]) / 75 * 100, 1),
    }
    SCORE_OUT.parent.mkdir(parents=True, exist_ok=True)
    SCORE_OUT.write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "req_api_07": new_status,
        "req_cv_05": score["req_cv_05_status"],
        "total_after": score["total_after"],
        "counts": counts,
        "compliance_pct": score["compliance_pct"],
        "verified_pct": score["verified_pct"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
