"""
Сборка итоговых матриц трассируемости GaugeVision AI 3.0 (ветка next-gen/integration):
  - reports/final_integration/RTM_ORIGINAL.csv — 75 требований из reports/industrial_validation/REQUIREMENTS_TRACEABILITY_MATRIX.csv;
  - reports/final_integration/RTM_NEXT_GEN.csv — 6 требований программы Next Generation;
  - reports/final_integration/evidence/score_final.json — сводный расчёт баллов по направлениям.

Методика расчёта балла (reports/industrial_validation/build_rtm_scada.py, reports/remediation/tests/build_rtm.py):
  балл направления = макс. балл × (PASS + 0,5 × PARTIAL) / число требований направления.
  FAIL и NOT VERIFIED дают 0.

Статус каждого требования вычисляется из фактических файлов доказательств; при отсутствии
доказательства присваивается NOT VERIFIED. Исторические каталоги (reports/audit,
reports/remediation, reports/industrial_validation, отчёты агентов) не изменяются.

Запуск:
  python -B reports/final_integration/build_rtm_final.py
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / "reports" / "final_integration"
EV = FIN / "evidence"
SRC_75 = ROOT / "reports" / "industrial_validation" / "REQUIREMENTS_TRACEABILITY_MATRIX.csv"
OUT_ORIG = FIN / "RTM_ORIGINAL.csv"
OUT_NG = FIN / "RTM_NEXT_GEN.csv"
OUT_SCORE = EV / "score_final.json"

MAX_POINTS: dict[str, int] = {
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


def load_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def parse_suite_summary(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 3 or not parts[1].startswith("rc="):
            continue
        name = parts[0]
        rc = int(parts[1].split("=", 1)[1])
        sec = parts[2]
        tail = parts[3] if len(parts) > 3 else ""
        out[name] = {"rc": rc, "passed": rc == 0, "sec": sec, "tail": tail}
    return out


def git_diff_empty(base_rev: str, rel_path: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), "-c", "safe.directory=*", "diff", "--quiet", base_rev, "--", rel_path],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def e2e_step(e2e: dict[str, Any] | None, num: int) -> dict[str, Any] | None:
    if not e2e:
        return None
    for s in e2e.get("steps") or []:
        if s.get("step") == num:
            return s
    return None


def fmt(val: float | int | None, digits: int = 1) -> str:
    if val is None:
        return "—"
    return f"{val:.{digits}f}".replace(".", ",")


def main() -> int:
    rows_75 = list(csv.DictReader(open(SRC_75, encoding="utf-8")))
    assert len(rows_75) == 75, f"Ожидалось 75 требований, получено {len(rows_75)}"

    # Загрузка финальных доказательств ветки next-gen/integration
    suites1 = parse_suite_summary(EV / "test_runs" / "suites_run1_summary.txt")
    suites2 = parse_suite_summary(EV / "test_runs" / "suites_rep2_summary.txt")
    suites3 = parse_suite_summary(EV / "test_runs" / "suites_rep3_summary.txt")
    audits = load_json(EV / "original_audit_rerun" / "rerun_summary.json")
    audit_01 = load_json(EV / "original_audit_rerun" / "audit_01_cv_regression" / "cv_regression_results.json")
    audit_02 = load_json(EV / "original_audit_rerun" / "audit_02_qos1_default" / "track2_audit_results.json")
    audit_03 = load_json(EV / "original_audit_rerun" / "audit_03_security_rbac_on" / "track1_security_audit_results.json")
    audit_04 = load_json(EV / "original_audit_rerun" / "audit_04_hmi_auth_off_compat" / "hmi_e2e_audit_results.json")
    audit_05 = load_json(EV / "original_audit_rerun" / "audit_05_soak_edge_cases" / "perf_soak_fault_results.json")
    interop = load_json(EV / "interop" / "interop_results.json")
    browser = load_json(EV / "browser_e2e" / "browser_e2e_report.json")
    hmi_30 = load_json(EV / "hmi" / "hmi_results.json")
    offline = load_json(EV / "offline_install" / "offline_install_results.json")
    soak = load_json(EV / "soak" / "soak_results.json")
    e2e5 = load_json(EV / "e2e" / "e2e_results_run5.json")
    e2e4 = load_json(EV / "e2e" / "e2e_results_run4.json")
    sec = load_json(EV / "security" / "security_audit_merged.json")
    static = load_json(EV / "static" / "static_scan.json")
    mig = load_json(EV / "migration" / "migration_copies.json")

    # Исторические доказательства этапов (только чтение)
    cv_v7 = load_json(ROOT / "reports" / "industrial_validation" / "results" / "final_v7" / "final_v7_summary.json")
    scada_30 = load_json(ROOT / "reports" / "industrial_validation" / "evidence" / "scada" / "reconciliation_30min_summary.json")
    scada_scen = load_json(ROOT / "reports" / "industrial_validation" / "evidence" / "scada" / "scada_scenarios_results.json")
    mg_final = load_json(ROOT / "reports" / "next_generation" / "evidence" / "multigauge" / "mg_real_mosaic_final.json")
    ac_final = load_json(ROOT / "reports" / "next_generation" / "evidence" / "autocal" / "autocal_final_manual.json")
    pred_test = load_json(ROOT / "reports" / "next_generation" / "evidence" / "predictive" / "predictive_validation_final_locked_test.json")
    ilp_ver = load_json(ROOT / "reports" / "next_generation" / "evidence" / "ilp" / "ilp_verification_and_scalability.json")
    usb_20 = load_json(ROOT / "reports" / "remediation" / "evidence" / "usb_camera" / "usb_camera_results.json")
    llm_20 = load_json(ROOT / "reports" / "remediation" / "evidence" / "llm" / "llm_local_results.json")

    streamer_unchanged = git_diff_empty("94e646e", "app/streamer.py")
    vision_unchanged = git_diff_empty("94e646e", "app/vision.py")

    # Базовые предикаты из доказательств
    def suite_ok(name: str) -> bool:
        return bool(suites1.get(name, {}).get("passed"))

    all_13_ok = len(suites1) == 13 and all(v["passed"] for v in suites1.values())
    rep3_ok = (
        all(suites1.get(k, {}).get("passed") for k in ("test_acceptance_independent", "test_final_integration", "test_demo_dashboard"))
        and all(suites2.get(k, {}).get("passed") for k in ("test_acceptance_independent", "test_final_integration", "test_demo_dashboard"))
        and all(suites3.get(k, {}).get("passed") for k in ("test_acceptance_independent", "test_final_integration", "test_demo_dashboard"))
    )
    audits_ok = bool(audits) and len(audits) == 6 and all(a.get("exit_code") == 0 for a in audits)
    interop_ok = bool(interop and interop.get("passed"))
    browser_ok = bool(browser and browser.get("passed"))
    hmi_30_ok = bool(
        hmi_30
        and all(
            not sz.get("errors")
            and not sz.get("failed_requests")
            and not sz.get("external_requests")
            and all(not v.get("hOverflow") for v in (sz.get("views") or {}).values())
            for sz in (hmi_30.get("sizes") or {}).values()
        )
    )
    offline_ok = bool(offline and offline.get("passed"))
    soak_ok = bool(
        soak
        and soak.get("duration_s", 0) >= 3600.0
        and soak.get("drained_after_end")
        and (soak.get("summary") or {}).get("server_errors") == 0
        and (soak.get("summary") or {}).get("modbus_errors") == 0
        and (soak.get("summary") or {}).get("mqtt_seq_gaps") == 0
    )
    e2e5_ok = bool(e2e5 and e2e5.get("passed") == 19 and e2e5.get("total") == 19)
    sec_ok = bool(sec and sec.get("all_passed") and sec.get("passed_checks") == 11)
    static_ok = bool(static and static.get("clean"))
    mig_ok = bool(mig and len(mig) >= 3 and all(m.get("passed") for m in mig))
    scada_30_ok = bool(
        scada_30
        and scada_scen
        and scada_30.get("actual_duration_s", 0) >= 1800.0
        and scada_30.get("good_quality_pct", 0) >= 99.0
        and scada_30.get("status_match_pct", 0) >= 95.0
        and all(bool(v.get("ok")) for v in (scada_scen.get("scenarios") or {}).values())
    )

    def pick(ok: bool | None, pass_txt: str, ev: str, notes: str = "", partial: bool = False) -> tuple[str, str, str, str]:
        if ok is None:
            return ("NOT VERIFIED", pass_txt, ev or "—", notes)
        if not ok:
            return ("FAIL", pass_txt, ev, notes)
        return ("PARTIAL" if partial else "PASS", pass_txt, ev, notes)

    # Извлекаем ключевые цифры из загруженных JSON
    ic = (interop or {}).get("checks") or {}
    rtsp_cv = ic.get("rtsp_cv") or {}
    mqtt_rec = ic.get("mqtt_delivery_reconciliation") or {}
    mb_py = ic.get("modbus_pymodbus") or {}
    ss = (soak or {}).get("summary") or {}
    soak_dur_min = round((soak or {}).get("duration_s", 0) / 60.0, 1)
    cpu_save = ((audit_05 or {}).get("adaptive_fps_cpu_comparison") or {}).get("measured_cpu_reduction_pct")
    off_c = (offline or {}).get("checks") or {}
    e5_s12 = (e2e_step(e2e5, 12) or {}).get("details") or {}
    e5_s13 = (e2e_step(e2e5, 13) or {}).get("details") or {}
    e5_s14 = (e2e_step(e2e5, 14) or {}).get("details") or {}
    e5_s19 = (e2e_step(e2e5, 19) or {}).get("details") or {}

    # Оценка 75 исходных требований
    eval_75: dict[str, tuple[str, str, str, str]] = {}

    # 1. Архитектурная видеоаналитика (11)
    eval_75["REQ-VA-01"] = pick(
        interop_ok and soak_ok,
        f"Реальный RTSP (mediamtx с аутентификацией + ffmpeg H.264): подключение {fmt(ic.get('rtsp_connect_s'), 2)} с, "
        f"{rtsp_cv.get('within_0_35_MPa_of_reference')}/{rtsp_cv.get('samples')} в ±0,35 МПа "
        f"(MAE {fmt(rtsp_cv.get('mae_vs_nearest_reference'), 4)} МПа), восстановление после обрыва издателя "
        f"{fmt(ic.get('rtsp_publisher_recovered_s'), 2)} с и сервера {fmt(ic.get('rtsp_server_recovered_s'), 2)} с. "
        f"В soak ({fmt(soak_dur_min, 1)} мин) 4 обрыва RTSP-издателя, все 4 восстановлены ({', '.join(fmt(x, 1) for x in ((soak or {}).get('rtsp') or {}).get('reconnect_s', []))} с)",
        "evidence/interop/interop_results.json; evidence/soak/soak_results.json",
    )
    eval_75["REQ-VA-02"] = pick(
        soak_ok and e2e5_ok,
        f"Локальный video_file через VideoFileWorker: непрерывно работал весь soak {fmt(soak_dur_min, 1)} мин (p50 {fmt((ss.get('fps_per_source') or {}).get('p50'), 2)} к/с) и в E2E прогоне 5 (19/19)",
        "evidence/soak/soak_results.json; evidence/e2e/e2e_results_run5.json",
    )
    if streamer_unchanged and usb_20 and usb_20.get("passed"):
        eval_75["REQ-VA-03"] = (
            "PASS",
            "Перенос доказательства версии 2.0 с оговоркой: app/streamer.py не изменялся с 94e646e (git diff пуст), "
            "веб-камера пользователя в этой приёмке не включалась. В 2.0 подтверждена USB/UVC-камера через DirectShow "
            "(подключение 2,0 с, 9,9 к/с, 189 кадров, освобождение после удаления)",
            "reports/remediation/evidence/usb_camera/usb_camera_results.json; KNOWN_LIMITATIONS.md § 5",
            "перенос с 2.0 (код streamer.py не менялся)",
        )
    else:
        eval_75["REQ-VA-03"] = (
            "NOT VERIFIED",
            "Захват с USB-камеры не проверялся на изменённом app/streamer.py",
            "—",
            "требуется прогон на USB-камере",
        )
    eval_75["REQ-VA-04"] = pick(
        soak_ok and interop_ok and audits_ok,
        f"Одновременные каналы с изоляцией сбоев: в soak {fmt(soak_dur_min, 1)} мин 2 независимых многоприборных источника "
        f"(video_file 8 приборов + RTSP 4 прибора = 12 приборов), при 4 обрывах RTSP первый источник оставался online; "
        f"в interop 2 стендовых канала оставались online при обрыве RTSP; в audit_02 масштабирование до 8 каналов без ошибок",
        "evidence/soak/soak_results.json; evidence/interop/interop_results.json; evidence/original_audit_rerun/audit_02_qos1_default/track2_audit_results.json",
    )
    eval_75["REQ-VA-05"] = pick(
        interop_ok and soak_ok,
        f"Автопереподключение RTSP с экспоненциальной задержкой: в interop {fmt(ic.get('rtsp_publisher_recovered_s'), 2)} с (издатель) "
        f"и {fmt(ic.get('rtsp_server_recovered_s'), 2)} с (сервер); в soak 4 цикла обрыва без вмешательства",
        "evidence/interop/interop_results.json; evidence/soak/soak_results.json",
    )
    eval_75["REQ-VA-06"] = pick(
        browser_ok and audits_ok,
        "Заморозка, темнота, пар и частичное перекрытие вычисляются по пикселям (audit_02: 11 сценариев без обходов); "
        "в browser_e2e пар и частичное перекрытие переводят канал в DEGRADED, восстановление — в ONLINE",
        "evidence/browser_e2e/browser_e2e_report.json; evidence/original_audit_rerun/audit_02_qos1_default/track2_audit_results.json",
        "DEF-11 устранён",
    )
    eval_75["REQ-VA-07"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok and browser_ok,
        "Детекция низкой освещённости, бликов, пара/задымления и 50 % перекрытия объектива подтверждена в audit_02, browser_e2e и test_acceptance_independent (21/21)",
        "evidence/original_audit_rerun/audit_02_qos1_default/track2_audit_results.json; evidence/browser_e2e/browser_e2e_report.json",
        "DEF-11 устранён",
    )
    # REQ-VA-08 остаётся PARTIAL: packet_loss_pct честно None, реальные сетевые потери RTP не измеряются
    rtsp_drop = ((ic.get("rtsp_outage_channel_diagnostics") or [{}])[0]).get("frame_drop_pct")
    eval_75["REQ-VA-08"] = pick(
        interop_ok and audits_ok,
        f"При обрыве RTSP в interop фиксируются пропуски кадров (frame_drop_pct = {fmt(rtsp_drop, 1)} %, статус OFFLINE), "
        f"соседние каналы не затронуты. Метрика packet_loss_pct честно остаётся null (OpenCV не отдаёт счётчики RTP), "
        f"измерение частичных сетевых потерь пакетов не реализовано и не испытывалось",
        "evidence/interop/interop_results.json; evidence/original_audit_rerun/audit_02_qos1_default/track2_audit_results.json",
        "фиктивные потери устранены; измерение сетевых потерь RTP — открыто",
        partial=True,
    )
    eval_75["REQ-VA-09"] = pick(
        audits_ok and suite_ok("test_remediation_full"),
        f"Adaptive FPS 1→6 к/с, переключение 0,016 мс (audit_02), измеренное снижение CPU в audit_05 на финальном коде — {fmt(cpu_save, 1)} %",
        "evidence/original_audit_rerun/audit_05_soak_edge_cases/perf_soak_fault_results.json; evidence/original_audit_rerun/audit_02_qos1_default/track2_audit_results.json",
        "DEF-12 устранён",
    )
    eval_75["REQ-VA-10"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok,
        "Кольцевой буфер pre/post: параллельные инциденты не теряются (audit_02: 2/2 архивированы, pre строго до триггера), "
        "клипы сохраняются на диск и восстанавливаются после перезапуска (test_acceptance_independent 21/21)",
        "evidence/test_runs/test_acceptance_independent.log; evidence/original_audit_rerun/audit_02_qos1_default/track2_audit_results.json",
        "DEF-10, NEW-08 устранены",
    )
    eval_75["REQ-VA-11"] = pick(
        browser_ok and soak_ok,
        "Диагностические API здоровья архитектуры (/api/health с loop_lag_ms, /api/architecture/*) и управляемая симуляция отказов проверены в browser_e2e и soak",
        "evidence/browser_e2e/browser_e2e_report.json; evidence/soak/soak_results.json",
    )

    # 2. Store-and-Forward и отказоустойчивость (12)
    eval_75["REQ-SF-01"] = pick(
        offline_ok and audits_ok,
        f"SQLite WAL подтверждён через PRAGMA journal_mode = {((off_c.get('sqlite') or {}).get('journal_mode'))} в чистой offline-установке и audit_02",
        "evidence/offline_install/offline_install_results.json; evidence/original_audit_rerun/audit_02_qos1_default/track2_audit_results.json",
        "DEF-19 устранён",
    )
    eval_75["REQ-SF-02"] = pick(
        interop_ok and soak_ok and e2e5_ok,
        f"Монотонный seq_id и уникальный event_uuid в каждой записи: в soak 1..{ss.get('mqtt_messages')} (0 разрывов), "
        f"в E2E прогоне 5 — 1..{(e5_s14.get('seq_range') or [None, None])[1]} (0 разрывов), в interop сверка по event_uuid",
        "evidence/soak/soak_results.json; evidence/e2e/e2e_results_run5.json; evidence/interop/interop_results.json",
    )
    eval_75["REQ-SF-03"] = pick(
        browser_ok and soak_ok and e2e5_ok,
        f"При обрыве связи телеметрия пишется в sf_queue (pending): в soak пик {ss.get('sf_pending_max')} зап., в E2E прогоне 5 — {e5_s13.get('pending')} зап., в browser_e2e — 2 зап.",
        "evidence/soak/soak_results.json; evidence/e2e/e2e_results_run5.json; evidence/browser_e2e/browser_e2e_report.json",
    )
    eval_75["REQ-SF-04"] = pick(
        interop_ok and e2e5_ok,
        f"События alarm/link/prediction копятся в sf_queue при отказе брокера (interop: {mqtt_rec.get('alarm_rows')} тревог; E2E прогон 5: alarm + prediction)",
        "evidence/interop/interop_results.json; evidence/e2e/e2e_results_run5.json",
    )
    eval_75["REQ-SF-05"] = pick(
        interop_ok and suite_ok("test_acceptance_independent"),
        f"Доставка кадров тревог через сторонний брокер amqtt: {mqtt_rec.get('frames_received')}/{mqtt_rec.get('alarm_rows_with_frame')} кадров, SHA-256 совпал у всех; после подтверждения байты кадра в очереди не хранятся",
        "evidence/interop/interop_results.json; evidence/test_runs/test_acceptance_independent.log",
        "DEF-06, NEW-02 устранены",
    )
    eval_75["REQ-SF-06"] = pick(
        interop_ok and soak_ok and e2e5_ok,
        f"Реальный останов брокера amqtt: в interop {mqtt_rec.get('sf_rows_sent')}/{mqtt_rec.get('sf_rows_total')} доставлено (0 потерь, BUFFERING через {fmt((ic.get('mqtt_outage_detection') or {}).get('detected_after_s'), 1)} с); "
        f"в soak 6 остановок по 60 с — {ss.get('mqtt_messages')}/{ss.get('sf_rows')} без потерь; "
        f"в E2E прогоне 5 HR 905 = 1 за {fmt(e5_s13.get('hr905_detect_s'), 1)} с (DEF-INT-04 закрыт)",
        "evidence/interop/interop_results.json; evidence/soak/soak_results.json; evidence/e2e/e2e_results_run5.json",
        "DEF-01, NEW-12, DEF-INT-04 устранены",
    )
    eval_75["REQ-SF-07"] = pick(
        interop_ok and soak_ok and e2e5_ok,
        f"Автоматическая пакетная досылка после возврата брокера: interop {fmt((ic.get('mqtt_recovery') or {}).get('drain_s'), 2)} с, "
        f"E2E прогон 5 — {fmt(e5_s14.get('drain_s'), 1)} с, soak — полное дренирование после всех 6 обрывов",
        "evidence/interop/interop_results.json; evidence/e2e/e2e_results_run5.json; evidence/soak/soak_results.json",
    )
    eval_75["REQ-SF-08"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok and soak_ok,
        "Строгий порядок ORDER BY seq_id ASC подтверждён при конкурентной записи/досылке (audit_02: 0 нарушений, 0 дублей) и в soak (10 309 записей без разрывов)",
        "evidence/original_audit_rerun/audit_02_qos1_default/track2_audit_results.json; evidence/soak/soak_results.json",
    )
    eval_75["REQ-SF-09"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok,
        "Сохранность pending-очереди после перезапуска во время обрыва: audit_02 (15 → 15, zero_loss_across_restart=true) и test_acceptance_independent",
        "evidence/original_audit_rerun/audit_02_qos1_default/track2_audit_results.json; evidence/test_runs/test_acceptance_independent.log",
    )
    eval_75["REQ-SF-10"] = pick(
        audits_ok,
        "Повторный обрыв в середине досылки (audit_02, сценарий E): 40 + 10 = 50 доставлено, pending = 0, total_accounted_for = true",
        "evidence/original_audit_rerun/audit_02_qos1_default/track2_audit_results.json",
    )
    eval_75["REQ-SF-11"] = pick(
        interop_ok and suite_ok("test_acceptance_independent"),
        f"At-least-once с event_uuid и сериализацией доставки: 0 дублей в interop (duplicate_deliveries = {mqtt_rec.get('duplicate_deliveries')}) и при конкурентной нагрузке",
        "evidence/interop/interop_results.json; evidence/test_runs/test_acceptance_independent.log",
        "DEF-21, NEW-03 устранены",
    )
    eval_75["REQ-SF-12"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok,
        "Ограничение очереди по строкам/МБ/диску: вытеснение старой телеметрии с сохранением тревог, журнал переполнения и флаг queue_overflow (audit_02 сценарий G: 60 → cap 30; acceptance 21/21)",
        "evidence/original_audit_rerun/audit_02_qos1_default/track2_audit_results.json; evidence/test_runs/test_acceptance_independent.log",
        "DEF-06 устранён",
    )

    # 3. API и промышленные интеграции (7)
    eval_75["REQ-API-01"] = pick(
        soak_ok and browser_ok and all_13_ok,
        "Все REST-маршруты треков 1, 2 и Next Gen работают без ошибок сервера (soak: 0 server_errors; browser_e2e: 36 позиций в демопрофиле, 13/13 наборов PASS)",
        "evidence/soak/soak_results.json; evidence/browser_e2e/browser_e2e_report.json; evidence/test_runs/suites_run1_summary.txt",
    )
    eval_75["REQ-API-02"] = pick(
        suite_ok("test_acceptance_independent") and suite_ok("test_final_integration") and sec_ok,
        "Невалидные JSON (NaN/Inf), некорректные параметры калибровки/оптимизатора, SSRF и Path Traversal возвращают 422/404 без HTTP 500 (SEC-05/06/07/08, new_api_security, acceptance 21/21)",
        "evidence/security/security_audit_merged.json; evidence/test_runs/test_final_integration.log; evidence/test_runs/test_acceptance_independent.log",
        "DEF-09 устранён",
    )
    eval_75["REQ-API-03"] = pick(
        browser_ok and suite_ok("test_acceptance_independent") and audits_ok,
        "WebSocket /ws/dashboard работает в browser_e2e и audit_04; отзыв сессии закрывает WS кодом 4401 (test_acceptance_independent)",
        "evidence/browser_e2e/browser_e2e_report.json; evidence/test_runs/test_acceptance_independent.log",
    )
    eval_75["REQ-API-04"] = pick(
        suite_ok("test_tracks_e2e") and suite_ok("test_remediation_full"),
        "SSE /api/events/stream защищён RBAC (401 без входа в audit_03), при авторизации отдаёт event: connected и живые события (test_tracks_e2e, test_remediation_full)",
        "evidence/test_runs/suites_run1_summary.txt; evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json",
    )
    eval_75["REQ-API-05"] = pick(
        interop_ok and suite_ok("test_modbus_register_map") and suite_ok("test_final_integration") and sec_ok,
        f"Modbus TCP read-only (FC 0x03/0x04, карта v2 + продление прогнозного блока до MAX_REGISTERS = 5208): "
        f"сторонний pymodbus {mb_py.get('matched_api_values')}/{mb_py.get('instruments_compared')} совпадений, STALE = NaN, "
        f"чужой unit_id → 0x0B; запись FC 0x06 → 0x01 и выход за границу 5208 → 0x02 (SEC-10, test_modbus_register_map, modbus_slots_lifecycle). "
        f"Примечание: старый скрипт interop 2.0 пробовал адрес 5000, который в 3.0 лежит внутри продлённого прогнозного блока 4096–5207",
        "evidence/interop/interop_results.json; evidence/security/security_audit_merged.json; evidence/test_runs/test_final_integration.log",
        "DEF-13, DEF-INT-01, DEF-INT-02, DEF-INT-04, DEF-INT-10 устранены",
    )
    eval_75["REQ-API-06"] = pick(
        interop_ok and soak_ok and e2e5_ok,
        f"MQTT 3.1.1 QoS 1 с PUBACK против стороннего брокера amqtt: в interop {mqtt_rec.get('sf_rows_sent')}/{mqtt_rec.get('sf_rows_total')}, "
        f"в soak {ss.get('mqtt_messages')} сообщ. без потерь, в E2E прогоне 5 — 416 сообщ. без разрывов seq_id; политика TLS вне loopback проверена (network_policy)",
        "evidence/interop/interop_results.json; evidence/soak/soak_results.json; evidence/e2e/e2e_results_run5.json",
        "DEF-01, DEF-13, OBS-SHARED-02 устранены",
    )
    eval_75["REQ-API-07"] = pick(
        scada_30_ok and e2e5_ok and bool((e2e_step(e2e5, 12) or {}).get("passed")) and bool((e2e_step(e2e5, 19) or {}).get("passed")),
        f"Лабораторный уровень (пробная лицензия 2 ч, один узел 127.0.0.1:15020, read-only): подтверждён обмен с реальной SCADA Ignition 8.3.10 — "
        f"30,6-мин сверка 36 приборов ({scada_30.get('total_compared_pairs') if scada_30 else 0} пар, Good quality {scada_30.get('good_quality_pct') if scada_30 else 0} %, "
        f"статусы {scada_30.get('status_match_pct') if scada_30 else 0} %) + повторный E2E прогон 5 на финальном коде (19/19: 8 приборов щита в Tag Historian Ignition, "
        f"Heartbeat {e5_s12.get('heartbeat_points')} точек, свободный слот IsNoData = {e5_s12.get('free_slot_isnodata')}, "
        f"обрыв связи за {fmt((e5_s19.get('ignition_link') or {}).get('link_lost_after_stop_s'), 1)} с, восстановление за {fmt((e5_s19.get('ignition_link') or {}).get('link_back_after_stop_s'), 1)} с). "
        f"Прогнозные регистры через Ignition и OPC UA — NOT VERIFIED; MasterSCADA не проверялась",
        "SCADA_REVALIDATION_REPORT.md; evidence/e2e/e2e_results_run5.json; reports/industrial_validation/SCADA_INTEGRATION_REPORT.md",
        "закрыт на лабораторном уровне (Ignition 8.3.10)",
    )

    # 4. Аналитика и умная диспетчеризация (9)
    eval_75["REQ-DA-01"] = pick(
        audits_ok and suite_ok("test_remediation_full"),
        "Классификация порогов LL/L/H/HH проверена в audit_01 (17 точек) и audit_03",
        "evidence/original_audit_rerun/audit_01_cv_regression/cv_regression_results.json; evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json",
    )
    eval_75["REQ-DA-02"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok,
        "Расчёт dV/dt и peak_rate_per_min по реальным меткам времени: audit_03 (линейный рост/спад ±6 МПа/мин — точное совпадение, скачок 4 МПа → гидроудар) и test_acceptance_independent (20 Гц опрос HMI без ложного гидроудара)",
        "evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json; evidence/test_runs/test_acceptance_independent.log",
        "DEF-14, NEW-01 устранены",
    )
    eval_75["REQ-DA-03"] = pick(
        audits_ok,
        "Амплитуда колебаний стрелки считается по фактическому ряду без подмены профилями (audit_03 сценарии 5 и 12: flat → chatter 0,0 %, ±0,5 МПа → 8,33 %)",
        "evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json",
        "DEF-08 устранён",
    )
    eval_75["REQ-DA-04"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok,
        "Учёт времени в зоне WARNING/CRITICAL без фантомных минут: audit_03 (при t = 0 с overload_min = 0,0) и test_acceptance_independent",
        "evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json; evidence/test_runs/test_acceptance_independent.log",
        "DEF-08 устранён",
    )
    eval_75["REQ-DA-05"] = pick(
        suite_ok("test_acceptance_independent"),
        "Частота срабатываний за реальные окна 12 ч / 24 ч подтверждена в test_acceptance_independent (dispatch_overload_trips_and_health_split)",
        "evidence/test_runs/test_acceptance_independent.log",
        "DEF-08 устранён",
    )
    eval_75["REQ-DA-06"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok,
        "Confidence YOLO и оптические дефекты учитываются в optical_health (audit_03 сценарии 9–10, test_acceptance_independent)",
        "evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json; evidence/test_runs/test_acceptance_independent.log",
    )
    eval_75["REQ-DA-07"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok,
        "Health Score в [0; 100] без NaN, отделён от оптики камеры (audit_03 сценарий 10: optical_score = 20,0, health_score = 100,0, modernization_needed = false)",
        "evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json; evidence/test_runs/test_acceptance_independent.log",
        "DEF-08 устранён",
    )
    eval_75["REQ-DA-08"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok,
        "Различение 3 классов первопричин + норма; деградация оптики не вызывает рекомендации модернизации (audit_03, test_acceptance_independent)",
        "evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json; evidence/test_runs/test_acceptance_independent.log",
        "DEF-08 устранён",
    )
    eval_75["REQ-DA-09"] = pick(
        suite_ok("test_acceptance_independent") and rep3_ok and browser_ok,
        "Автотриггер ТЗ формирует .md и .docx, персистентен, без дублей и доступен в HMI (auto_spec_generation_lifecycle 3/3 прогонов после исправления DEF-INT-08, browser_e2e)",
        "evidence/test_runs/test_acceptance_independent.log; evidence/browser_e2e/browser_e2e_report.json",
        "DEF-20, DEF-INT-08 устранены",
    )

    # 5. Генерация инженерной документации (10)
    eval_75["REQ-DOC-01"] = pick(
        browser_ok and offline_ok and soak_ok and e2e5_ok and sec_ok,
        f"Валидный OpenXML .docx со штампами, таблицами и XML-экранированием: offline ({(off_c.get('docx') or {}).get('bytes')} Б), "
        f"soak (13/13 генераций, p50 {fmt(((ss.get('ops') or {}).get('spec_docx') or {}).get('p50_ms'), 1)} мс), "
        f"E2E прогон 5 ({(e2e_step(e2e5, 17) or {}).get('details', {}).get('docx_bytes')} Б), SEC-06 (контроль управляющих символов)",
        "evidence/offline_install/offline_install_results.json; evidence/soak/soak_results.json; evidence/e2e/e2e_results_run5.json",
    )
    eval_75["REQ-DOC-02"] = pick(
        browser_ok and hmi_30_ok and e2e5_ok,
        "Мгновенный предпросмотр и скачивание .md проверены в browser_e2e, hmi_results (3 разрешения) и E2E прогоне 5",
        "evidence/browser_e2e/browser_e2e_report.json; evidence/hmi/hmi_results.json; evidence/e2e/e2e_results_run5.json",
    )
    eval_75["REQ-DOC-03"] = pick(
        audits_ok and browser_ok,
        "Все 5 разделов ТЗ (паспорт, протокол, ведомость, ТЗ, ТЭО) подтверждены в .md и .docx (audit_04: docx_has_all_5_sections=true, md_has_all_5_sections=true)",
        "evidence/original_audit_rerun/audit_04_hmi_auth_off_compat/hmi_e2e_audit_results.json; evidence/browser_e2e/browser_e2e_report.json",
    )
    eval_75["REQ-DOC-04"] = pick(
        suite_ok("test_acceptance_independent") and e2e5_ok,
        f"Протокол мониторинга строится по реальным данным SQLite за выбранный период (test_acceptance_independent: period_stats_sql_vs_reference, api_period_sensitivity_from_db; "
        f"E2E прогон 5 шаг 18: db_samples_in_doc = {(e2e_step(e2e5, 18) or {}).get('details', {}).get('db_samples_in_doc')} = db_rows)",
        "evidence/test_runs/test_acceptance_independent.log; evidence/e2e/e2e_results_run5.json",
        "DEF-03, NEW-05, NEW-06 устранены",
    )
    eval_75["REQ-DOC-05"] = pick(
        audits_ok and suite_ok("test_tracks_e2e") and offline_ok,
        "Встраивание 4 изображений аномалий в .docx подтверждено (audit_04: docx_media_images_count=4, offline: media=4, test_tracks_e2e: media_imgs=4)",
        "evidence/original_audit_rerun/audit_04_hmi_auth_off_compat/hmi_e2e_audit_results.json; evidence/offline_install/offline_install_results.json",
        "DEF-04 устранён",
    )
    eval_75["REQ-DOC-06"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok,
        "Исправное оборудование не попадает в дефектную ведомость (audit_03 case1: defective=0, CAPEX=0), неизвестный фильтр → 0/422, единичное срабатывание без CAPEX",
        "evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json; evidence/test_runs/test_acceptance_independent.log",
        "DEF-04, DEF-17 устранены",
    )
    eval_75["REQ-DOC-07"] = pick(
        audits_ok,
        "Автоформирование требований 4–20 мА/HART/RS-485, IP65/67 и Ex-защиты для газовых зон подтверждено (audit_03: gas_sensor_ex = 1Ex ia IIC T6 Ga (ТР ТС 012/2011))",
        "evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json",
        "DEF-04 устранён",
    )
    eval_75["REQ-DOC-08"] = pick(
        suite_ok("test_acceptance_independent") and audits_ok,
        "Арифметика CAPEX/OPEX/эффект/окупаемость сверена с формулами; при CAPEX = 0 окупаемость null (audit_03 case7; case3: 230 280 ₽, чистый эффект 540 000 ₽/год, 5 мес.)",
        "evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json; evidence/test_runs/test_acceptance_independent.log",
        "DEF-04 устранён",
    )
    eval_75["REQ-DOC-09"] = pick(
        offline_ok and audits_ok,
        "100 % автономная воспроизводимая генерация без сети: audit_03 case9 (идентичный MD на одинаковых входах, меняется при мутации), offline-установка: 0 внешних запросов",
        "evidence/offline_install/offline_install_results.json; evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json",
    )
    eval_75["REQ-DOC-10"] = pick(
        audits_ok and suite_ok("test_acceptance_independent") and suite_ok("test_final_integration") and bool(llm_20 and llm_20.get("passed")),
        "Протокол OpenAI-compatible API и безопасный fallback при 500/bad JSON/таймауте/пустом ответе рассуждающей модели проверены на финальном коде "
        "(audit_03, test_acceptance_independent, SSRF-фильтр network_policy OBS-SHARED-04). Живой прогон с локальной Ollama qwen3.5 не повторялся из-за запрета нагрузки GPU — "
        "перенесено подтверждение 2.0 (llm_local_results.json)",
        "evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json; evidence/test_runs/test_final_integration.log; reports/remediation/evidence/llm/llm_local_results.json",
        "NEW-13, OBS-SHARED-04 устранены",
    )

    # 6. Корректность и сохранение CV-инференса (6)
    eval_75["REQ-CV-01"] = pick(
        offline_ok and audits_ok,
        f"Локальные веса models/gauge_yolov8.pt ({(off_c.get('yolo_weights') or {}).get('bytes')} Б) загружаются на CPU без сети в чистой offline-установке и audit_01",
        "evidence/offline_install/offline_install_results.json; evidence/original_audit_rerun/audit_01_cv_regression/cv_regression_results.json",
    )
    cw = (audit_01 or {}).get("cw_sweep_0_16_mpa") or {}
    eval_75["REQ-CV-02"] = pick(
        audits_ok and cw.get("n_missed") == 0,
        f"Точное считывание CW (0/360°), CCW и отрицательных шкал в audit_01 на финальном коде: "
        f"CW {cw.get('n_valid')}/{cw.get('n_total')} (MAE {fmt(cw.get('mae_pct_fs'), 3)} % шкалы), "
        f"CCW 5/5 (MAE {fmt(((audit_01 or {}).get('ccw_scale') or {}).get('mae_pct'), 3)} %), "
        f"отрицательная шкала 5/5 (MAE {fmt(((audit_01 or {}).get('negative_range') or {}).get('mae_kpa'), 3)} кПа)",
        "evidence/original_audit_rerun/audit_01_cv_regression/cv_regression_results.json",
    )
    eval_75["REQ-CV-03"] = pick(
        audits_ok and suite_ok("test_acceptance_independent"),
        "Отбраковка пустых кадров, мёртвой зоны, бликов и 44 % перекрытия подтверждена в audit_01; в 3.0 добавлен многоприборный режим (Multi-Gauge) на одном кадре",
        "evidence/original_audit_rerun/audit_01_cv_regression/cv_regression_results.json; evidence/e2e/e2e_results_run5.json",
        "DEF-02, DEF-15 устранены",
    )
    eval_75["REQ-CV-04"] = pick(
        interop_ok and audits_ok and suite_ok("test_demo_dashboard"),
        f"Сквозной цикл WSS смартфона-камеры 13,0→14,8→15,7→13,0 с записью в SQLite и событиями проверен в audit_04 (20/23 годных, уровни normal/warning/alert), "
        f"interop (221/221 ack) и test_demo_dashboard (3/3 прогонов)",
        "evidence/original_audit_rerun/audit_04_hmi_auth_off_compat/hmi_e2e_audit_results.json; evidence/interop/interop_results.json; evidence/test_runs/suites_run1_summary.txt",
    )
    # REQ-CV-05: PARTIAL по CV_VALIDATION_REPORT.md и final_v7_summary.json
    if cv_v7:
        cv_p = (cv_v7.get("sets") or {}).get("primary", {}).get("overall") or {}
        cv_u = (cv_v7.get("unusable") or {}).get("overall") or {}
        eval_75["REQ-CV-05"] = (
            "PARTIAL",
            f"Количественная валидация v7 на реальных фото MeterFL/MeasureBench (primary n = {cv_p.get('n')}): "
            f"локализация {fmt((cv_p.get('det_rate') or 0) * 100, 1)} % (ориентир ≥ 95 %), "
            f"достоверных {fmt((cv_p.get('valid_rate') or 0) * 100, 1)} % (≥ 90 %), "
            f"MAE {fmt((cv_p.get('mean_err_norm') or 0) * 100, 1)} % (≤ 2 %), "
            f"p95 {fmt((cv_p.get('p95_err_norm') or 0) * 100, 1)} % (≤ 5 %), "
            f"грубых {fmt((cv_p.get('gross_rate_valid') or 0) * 100, 1)} % (≤ 1 %); "
            f"отказ на непригодных кадрах (n = {cv_u.get('n')}) — {fmt((cv_u.get('correct_refusal_rate') or 0) * 100, 1)} % (ориентир ≥ 95 % выполнен). "
            f"Целевая точность не достигнута, принадлежность фото действующим цехам не подтверждена",
            "reports/industrial_validation/CV_VALIDATION_REPORT.md; reports/industrial_validation/results/final_v7/final_v7_summary.json",
            "DEF-22 (п. 1) закрыт частично; полевая валидация и точность открыты",
        )
    else:
        eval_75["REQ-CV-05"] = ("NOT VERIFIED", "Отсутствует final_v7_summary.json", "—", "DEF-22 открыт")

    # REQ-CV-06: NOT VERIFIED — GPU в этой приёмке не проверялся, а app/vision.py изменён с 2.0
    if vision_unchanged:
        eval_75["REQ-CV-06"] = ("NOT VERIFIED", "GPU-прогон в финальной приёмке не выполнялся (запрет нагрузки RTX 5060)", "—", "требуется прогон GPU")
    else:
        eval_75["REQ-CV-06"] = (
            "NOT VERIFIED",
            "GPU в финальной приёмке не проверялся (строго CPU-режим; нагрузка RTX 5060 на ноутбуке запрещена). "
            "После проверки 2.0 файл app/vision.py существенно изменён (+376/−61 строк, Multi-Gauge и доработка v7), "
            "поэтому прежнее доказательство 2.0 не переносится; требуется отдельный прогон на целевом GPU",
            "KNOWN_LIMITATIONS.md § 2; evidence/original_audit_rerun/audit_01_cv_regression/cv_regression_results.json",
            "требуется повторная проверка на GPU",
        )

    # 7. Функциональность и качество HMI (7)
    eval_75["REQ-HMI-01"] = pick(
        browser_ok and hmi_30_ok,
        "Переключение контуров Мониторинг / Видеоаналитика / Диспетчеризация и ТЗ + новая вкладка «Щит» без перезагрузки (browser_e2e и hmi_results 3 разрешения)",
        "evidence/browser_e2e/browser_e2e_report.json; evidence/hmi/hmi_results.json",
    )
    eval_75["REQ-HMI-02"] = pick(
        browser_ok and audits_ok,
        "Интерактивная топология, сетка камер, фокус и инспекторы Modbus/MQTT проверены в browser_e2e и audit_04",
        "evidence/browser_e2e/browser_e2e_report.json; evidence/original_audit_rerun/audit_04_hmi_auth_off_compat/hmi_e2e_audit_results.json",
    )
    eval_75["REQ-HMI-03"] = pick(
        browser_ok and audits_ok,
        f"Кнопка симуляции обрыва связи с АСУ ТП в HMI: очередь выросла (pending = {((browser or {}).get('steps') or {}).get('outage', {}).get('pendingDuringOutage')}), "
        f"после восстановления дослана за {((browser or {}).get('steps') or {}).get('outage', {}).get('drainMs')} мс",
        "evidence/browser_e2e/browser_e2e_report.json",
    )
    eval_75["REQ-HMI-04"] = pick(
        browser_ok and hmi_30_ok,
        "Матрица Health Score (36 позиций), тренды, рекомендации, лента инцидентов, плюс новые секции прогноза (41 строка), оптимизатора и кривой Парето",
        "evidence/browser_e2e/browser_e2e_report.json; evidence/hmi/hmi_results.json",
        "DEF-18, DEF-INT-07 устранены",
    )
    eval_75["REQ-HMI-05"] = pick(
        browser_ok and hmi_30_ok,
        "Выбор периода/скоупа, правка реквизитов, живой предпросмотр, сохранение плана модернизации и скачивание .docx/.md подтверждены в browser_e2e и hmi_results",
        "evidence/browser_e2e/browser_e2e_report.json; evidence/hmi/hmi_results.json",
    )
    eval_75["REQ-HMI-06"] = pick(
        browser_ok and hmi_30_ok,
        "Нулевое горизонтальное переполнение и отсутствие усечения элементов на 1920×1080, 1440×900 и 1280×720 во всех вкладках включая «Щит» (правка шапки 1701–1980 px в f3dea4d)",
        "evidence/browser_e2e/browser_e2e_report.json; evidence/hmi/hmi_results.json",
        "DEF-16 устранён",
    )
    eval_75["REQ-HMI-07"] = pick(
        browser_ok and hmi_30_ok and static_ok,
        "0 ошибок JS/консоли, 0 PageError, 0 HTTP 4xx/5xx, 0 внешних запросов и 0 символов middle dot (U+00B7) в UI (browser_e2e, hmi_results, static_scan)",
        "evidence/browser_e2e/browser_e2e_report.json; evidence/hmi/hmi_results.json; evidence/static/static_scan.json",
    )

    # 8. Безопасность и автономность (6)
    eval_75["REQ-SEC-01"] = pick(
        offline_ok and browser_ok and hmi_30_ok and sec_ok,
        "0 внешних запросов в браузере (browser_e2e, hmi_results), 0 обращений сервера по runtime_network_audit (offline_install), 0 внешних CDN-ресурсов и ссылок (SEC-11, OBS-SHARED-05)",
        "evidence/offline_install/offline_install_results.json; evidence/hmi/hmi_results.json; evidence/security/security_audit_merged.json",
        "NEW-11, OBS-SHARED-05 устранены",
    )
    eval_75["REQ-SEC-02"] = pick(
        offline_ok,
        f"Чистая установка из wheelhouse ({(off_c.get('wheelhouse') or {}).get('files')} файлов, {(off_c.get('wheelhouse') or {}).get('size_mb')} МБ) без сети за {fmt((off_c.get('pip_install') or {}).get('seconds'), 1)} с: "
        f"{(off_c.get('lock_vs_installed') or {}).get('lock_entries')}/61 пакетов совпали с lock, pip check = 0, YOLOv8 на CPU работает",
        "evidence/offline_install/offline_install_results.json; OFFLINE_DEPLOYMENT_REPORT.md",
        "DEF-05, NEW-09 устранены",
    )
    eval_75["REQ-SEC-03"] = pick(
        sec_ok and interop_ok and suite_ok("test_acceptance_independent"),
        "Учётные данные RTSP шифруются в SQLite (Fernet), маскируются в API и логах (interop: 0 утечек пароля и токенов; SEC-08 PASS)",
        "evidence/security/security_audit_merged.json; evidence/interop/interop_results.json",
        "DEF-07, NEW-10 устранены",
    )
    eval_75["REQ-SEC-04"] = pick(
        sec_ok and suite_ok("test_acceptance_independent") and suite_ok("test_final_integration"),
        "SSRF и Path Traversal отклоняются (422) на видеоисточниках и адресе LLM (SEC-08, test_acceptance_independent, network_policy OBS-SHARED-04)",
        "evidence/security/security_audit_merged.json; evidence/test_runs/test_final_integration.log",
        "DEF-07, OBS-SHARED-04 устранены",
    )
    eval_75["REQ-SEC-05"] = pick(
        sec_ok and suite_ok("test_acceptance_independent") and suite_ok("test_final_integration"),
        "RBAC на всех старых и новых маршрутах (Multi-Gauge, прогноз, оптимизатор, паспорта), lockout 429, защитные заголовки CSP/XFO/nosniff, сетевая политика OBS-SHARED-01..05 (11/11 аудита + new_api_security)",
        "evidence/security/security_audit_merged.json; SECURITY_FINAL_REPORT.md; evidence/test_runs/test_final_integration.log",
        "DEF-07, DEF-20, NEW-04, OBS-SHARED-01..05 устранены",
    )
    eval_75["REQ-SEC-06"] = pick(
        browser_ok and e2e5_ok and suite_ok("test_final_integration"),
        "Явное разграничение с СИ ФЗ-102 и ПАЗ в HMI и .docx; устаревшие и свободные каналы выдают NaN и STALE в Modbus (DEF-INT-01/02 закрыты; stream_loss_and_recovery, E2E шаг 12)",
        "evidence/browser_e2e/browser_e2e_report.json; evidence/e2e/e2e_results_run5.json; evidence/test_runs/test_final_integration.log",
        "DEF-22 (п. 4), DEF-INT-01, DEF-INT-02 устранены",
    )

    # 9. Архитектура и качество кода (4)
    eval_75["REQ-ARCH-01"] = pick(
        static_ok,
        f"Статический скан {(static or {}).get('files_scanned')} файлов: 0 TODO/FIXME, 0 NotImplementedError, 0 жёстких абсолютных путей, 0 middle dot в UI",
        "evidence/static/static_scan.json",
    )
    eval_75["REQ-ARCH-02"] = pick(
        offline_ok and static_ok,
        "Относительные пути от корня репозитория и конфигурация через .env.example подтверждены в offline-установке и статическом скане",
        "evidence/offline_install/offline_install_results.json; evidence/static/static_scan.json",
    )
    eval_75["REQ-ARCH-03"] = pick(
        audits_ok and suite_ok("test_acceptance_independent") and suite_ok("test_autocal"),
        "Производственная аналитика отделена от демопрофиля; исследовательский модуль app/autocal.py изолирован и не подключён к сервису",
        "evidence/original_audit_rerun/audit_03_security_rbac_on/track1_security_audit_results.json; evidence/test_runs/suites_run1_summary.txt",
        "DEF-08, DEF-11 устранены",
    )
    eval_75["REQ-ARCH-04"] = pick(
        mig_ok and suite_ok("test_final_integration") and suite_ok("test_acceptance_independent") and e2e5_ok,
        "Сериализация S&F, отбраковка отсчётов устаревшей calibration_rev (DEF-INT-03), сохранность журналов и данных при рестарте (E2E шаг 19), "
        "миграция БД всех 4 версий (1.0, 2.0, platform, analytics-validation) и 3 реальных локальных копий без потерь",
        "DATABASE_MIGRATION_REPORT.md; evidence/migration/migration_copies.json; evidence/e2e/e2e_results_run5.json",
        "DEF-02, DEF-10, DEF-20, DEF-INT-03 устранены",
    )

    # 10. Тестирование и воспроизводимость (3)
    eval_75["REQ-QA-01"] = pick(
        all_13_ok and rep3_ok,
        "Все 13 тестовых наборов (включая прежние test_demo_dashboard, test_tracks_e2e, test_remediation_full) проходят с кодом 0; повторяемость 3/3 подряд на финальном коде",
        "TEST_RESULTS.md; evidence/test_runs/suites_run1_summary.txt; evidence/test_runs/suites_rep2_summary.txt; evidence/test_runs/suites_rep3_summary.txt",
    )
    eval_75["REQ-QA-02"] = pick(
        suite_ok("test_acceptance_independent") and suite_ok("test_final_integration") and interop_ok and sec_ok,
        "Покрытие негативных и граничных сценариев: 21 проверка acceptance, 12 стыковых проверок test_final_integration, 11 проверок безопасности, 14 граничных случаев ILP, сторонние amqtt/pymodbus/mediamtx/ffmpeg",
        "TEST_RESULTS.md; evidence/test_runs/test_final_integration.log; evidence/interop/interop_results.json; evidence/security/security_audit_merged.json",
    )
    eval_75["REQ-QA-03"] = pick(
        soak_ok and offline_ok,
        f"Чистая offline-установка из wheelhouse без сети + непрерывный soak {fmt(soak_dur_min, 1)} мин на CPU "
        f"(12 приборов, video_file + RTSP, 6 обрывов брокера, 4 обрыва RTSP, 122 прогноза, 13 ILP, 13 DOCX): "
        f"0 ошибок сервера, 0 ошибок Modbus, 10 309/10 309 MQTT без разрывов, утечек памяти нет (RSS {fmt((ss.get('rss_mb') or {}).get('start'), 1)} → {fmt((ss.get('rss_mb') or {}).get('end'), 1)} МБ)",
        "SOAK_TEST_REPORT.md; OFFLINE_DEPLOYMENT_REPORT.md; evidence/soak/soak_results.json; evidence/offline_install/offline_install_results.json",
        "DEF-05, DEF-22 (п. 2, 3) устранены",
    )

    # Запись RTM_ORIGINAL.csv и расчёт баллов по 10 направлениям
    out_orig_rows: list[dict[str, Any]] = []
    agg: dict[str, dict[str, int]] = {}
    for r in rows_75:
        rid = r["ID"]
        st, actual, ev, defects = eval_75.get(rid, ("NOT VERIFIED", "Нет доказательства", "—", ""))
        d = agg.setdefault(r["Направление"], {"PASS": 0, "PARTIAL": 0, "FAIL": 0, "NOT VERIFIED": 0, "n": 0})
        d[st] += 1
        d["n"] += 1
        out_orig_rows.append({
            "ID": rid,
            "Направление": r["Направление"],
            "Требование": r["Требование"],
            "Приоритет": r["Приоритет"],
            "Ожидаемый результат (критерий аудита)": r["Ожидаемый результат (критерий аудита)"],
            "Статус аудита Gemini": r["Статус аудита Gemini"],
            "Статус 2.0 / SCADA": r["Статус повторной приёмки"],
            "Статус 3.0 (итог)": st,
            "Фактический результат 3.0": actual,
            "Доказательство": ev,
            "Дефекты аудита": r["Дефекты аудита"],
            "Состояние дефектов": defects or r["Состояние дефектов"],
        })

    with open(OUT_ORIG, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_orig_rows[0].keys()))
        w.writeheader()
        w.writerows(out_orig_rows)

    total_pts = 0.0
    dirs_score: dict[str, dict[str, Any]] = {}
    for name, mx in MAX_POINTS.items():
        d = agg[name]
        pts = mx * (d["PASS"] + 0.5 * d["PARTIAL"]) / d["n"]
        total_pts += pts
        dirs_score[name] = {**d, "max": mx, "points": round(pts, 2), "points_exact": round(pts, 6)}

    counts_75 = {k: sum(d[k] for d in agg.values()) for k in ("PASS", "PARTIAL", "FAIL", "NOT VERIFIED")}

    # Сборка RTM_NEXT_GEN.csv (6 требований Next Generation)
    ng_rows: list[dict[str, Any]] = []

    # 1. REQ-CV-05
    ng_rows.append({
        "ID": "REQ-CV-05",
        "Компонент": "Валидация CV на реальных фото",
        "Ветка-источник": "next-gen/platform",
        "Критерий приёмки": "Локализация ≥ 95 %, годных ≥ 90 %, MAE ≤ 2 %, p95 ≤ 5 %, грубых ≤ 1 %, отказ на непригодных ≥ 95 % на независимых реальных фото",
        "Статус": eval_75["REQ-CV-05"][0],
        "Фактический результат": eval_75["REQ-CV-05"][1],
        "Доказательство": eval_75["REQ-CV-05"][2],
        "Ограничения и дефекты": "Выполнен 1 из 6 ориентиров (отказ на непригодных 98,0 %); полевая валидация в цеху не проводилась",
    })

    # 2. REQ-API-07
    ng_rows.append({
        "ID": "REQ-API-07",
        "Компонент": "Стыковка с реальной SCADA (Ignition 8.3.10)",
        "Ветка-источник": "next-gen/scada-ignition → analytics-validation",
        "Критерий приёмки": "Реальный обмен Modbus TCP (read-only) с Ignition 8.3.10, мнемосхема Perspective, ≥ 30 мин сверки, сценарии отказов и E2E на объединённом коде",
        "Статус": eval_75["REQ-API-07"][0],
        "Фактический результат": eval_75["REQ-API-07"][1],
        "Доказательство": eval_75["REQ-API-07"][2],
        "Ограничения и дефекты": "Лабораторный уровень (пробная лицензия 2 ч, один узел 127.0.0.1); прогнозные регистры в Ignition и OPC UA — NOT VERIFIED; MasterSCADA не проверялась",
    })

    # 3. NG-MG-01
    if mg_final and suite_ok("test_multigauge") and suite_ok("test_multigauge_api") and e2e5_ok:
        res_by_n = {r["gauges_per_frame"]: r for r in mg_final.get("results") or []}
        r1 = res_by_n.get(1, {})
        r8 = res_by_n.get(8, {})
        r16 = res_by_n.get(16, {})
        mg_status = "PARTIAL"
        mg_fact = (
            f"На синтетическом щите 1–16 приборов: 0 ID Switch, 100 % годных, изоляция перекрытого прибора 7/7; "
            f"в E2E прогоне 5 на объединённом коде 8 приборов на синтетическом видео — 19/19 PASS (ошибка 0,07–0,42 % шкалы). "
            f"На мозаиках реальных фото MeterFL (final): при N ≤ 8 регистрация ≥ {fmt(min(r['registered_pct'] for n, r in res_by_n.items() if n <= 8), 1)} %, "
            f"медиана {fmt((r8.get('multi') or {}).get('median'), 2)}–1,53 %, 0 ID Switch; "
            f"однако при N = 1 хвост p95 = {fmt((r1.get('multi') or {}).get('p95'), 1)} % (грубых {fmt((r1.get('multi') or {}).get('gross'), 1)} %), "
            f"а при N = 16 годных {fmt(r16.get('valid_pct_of_all'), 1)} % (безопасно, грубых 0 %). Видео реального цехового щита не испытывалось"
        )
        mg_ev = "reports/next_generation/MULTI_GAUGE_VALIDATION.md; reports/next_generation/evidence/multigauge/mg_real_mosaic_final.json; evidence/e2e/e2e_results_run5.json"
    else:
        mg_status, mg_fact, mg_ev = "NOT VERIFIED", "Нет доказательств Multi-Gauge", "—"
    ng_rows.append({
        "ID": "NG-MG-01",
        "Компонент": "Multi-Gauge Vision (щит приборов)",
        "Ветка-источник": "next-gen/platform",
        "Критерий приёмки": "Несколько логических приборов на одном видеоисточнике, устойчивые ID, по-приборная калибровка/телеметрия/Modbus, валидация на реальных мозаиках",
        "Статус": mg_status,
        "Фактический результат": mg_fact,
        "Доказательство": mg_ev,
        "Ограничения и дефекты": "PARTIAL: тяжёлый хвост на final при N = 1 (p95 30,7 %), при N = 16 годных 47,9 %, нет видео реального щита",
    })

    # 4. NG-AC-01
    if ac_final and suite_ok("test_autocal") and suite_ok("test_final_integration"):
        acs = ac_final.get("summary") or {}
        gates_ok = sum(1 for v in (acs.get("gates") or {}).values() if v)
        ac_status = "FAILED"
        ac_fact = (
            f"На независимой выборке final (n = {acs.get('images')}, {acs.get('models')} групп) выполнен {gates_ok} из 5 критериев допуска (только время {fmt(acs.get('median_ms'), 0)} мс): "
            f"покрытие {fmt(acs.get('coverage_pct'), 1)} % (порог ≥ 50 %), точных среди принятых {fmt(acs.get('accurate_of_accepted_pct'), 1)} % (≥ 90 %), "
            f"грубых {fmt(acs.get('gross_of_all_pct'), 1)} % / {fmt(acs.get('gross_of_accepted_pct'), 1)} % (≤ 1 % / ≤ 2 %), "
            f"пределы верны {fmt(acs.get('limits_ok_of_accepted_pct'), 1)} % (≥ 95 %). "
            f"Модуль app/autocal.py выключен и не подключён к API и пульту (подтверждено test_autocal и autocal_cannot_apply)"
        )
        ac_ev = "reports/next_generation/AUTO_CALIBRATION_REPORT.md; reports/next_generation/evidence/autocal/autocal_final_manual.json; evidence/test_runs/test_final_integration.log"
    else:
        ac_status, ac_fact, ac_ev = "NOT VERIFIED", "Нет доказательств Auto Calibration", "—"
    ng_rows.append({
        "ID": "NG-AC-01",
        "Компонент": "Auto Calibration (автокалибровка по фото)",
        "Ветка-источник": "next-gen/platform",
        "Критерий приёмки": "Допуск по 5 критериям G1–G5 на независимой выборке final; при невыполнении — не включается в продукт",
        "Статус": ac_status,
        "Фактический результат": ac_fact,
        "Доказательство": ac_ev,
        "Ограничения и дефекты": "FAILED: в продукт не включено (ни auto, ни assisted); калибровка остаётся ручной по кадру",
    })

    # 5. NG-PA-01
    if pred_test and suite_ok("test_predictive_analytics") and suite_ok("test_final_integration") and e2e5_ok:
        pc = pred_test.get("clean") or {}
        br = (pc.get("threshold_breach_eta_h30") or {}).get("current_gv") or {}
        an = pc.get("anomaly_detection_labeled") or {}
        e5_s9 = (e2e_step(e2e5, 9) or {}).get("details") or {}
        pa_status = "PARTIAL"
        pa_fact = (
            f"На 4 реальных промышленных датасетах LOCKED TEST (82 ряда, 3 690 origins/горизонт) модель превосходит все 5 baseline на Gas Turbine и MetroPT-3 (H = 60), "
            f"покрытие PI95 83,4–91,1 %; однако recall предсказания пробоя уставки за 30 шагов составляет лишь {fmt(br.get('recall_pct'), 2)} % "
            f"(FNR {fmt(br.get('fnr_missed_pct'), 2)} %, Precision {fmt(br.get('precision_pct'), 2)} %, FAR {fmt(br.get('far_false_alarm_pct'), 2)} %), "
            f"а детектор аномалий на SKAB+MetroPT-3 даёт F1 = {fmt(an.get('f1_pct'), 2)} % при FAR = {fmt(an.get('far_pct'), 2)} %. "
            f"На синтетическом линейном дрейфе CV после усреднения по корзинам 30 с (DEF-INT-13): E2E прогон 5 ETA {fmt(e5_s9.get('eta_alert_min'), 2)} мин при истинных {fmt(e5_s9.get('true_eta_min'), 1)} мин "
            f"(отношение {fmt(e5_s9.get('eta_ratio'), 2)}), событие prediction доходит до журнала, SQLite и MQTT без дублей"
        )
        pa_ev = "reports/next_generation/PREDICTIVE_REAL_DATA_VALIDATION.md; reports/next_generation/evidence/predictive/predictive_validation_final_locked_test.json; evidence/e2e/e2e_results_run5.json"
    else:
        pa_status, pa_fact, pa_ev = "NOT VERIFIED", "Нет доказательств Predictive Analytics", "—"
    ng_rows.append({
        "ID": "NG-PA-01",
        "Компонент": "Predictive Analytics (прогноз и аномалии)",
        "Ветка-источник": "next-gen/analytics-validation",
        "Критерий приёмки": "Прогноз трендов, интервалы PI80/PI95, ETA до уставок, события prediction и валидация на реальных промышленных рядах",
        "Статус": pa_status,
        "Фактический результат": pa_fact,
        "Доказательство": pa_ev,
        "Ограничения и дефекты": "PARTIAL: recall пробоя уставки 4,65 % на реальных рядах, FAR аномалий 36,1 %; открыт DEF-INT-12 (расхождение описания режима в отчёте)",
    })

    # 6. NG-MO-01
    if ilp_ver and suite_ok("test_modernization_optimizer") and e2e5_ok and hmi_30_ok:
        pa15 = ilp_ver.get("part_a_small_1500") or {}
        pb14 = ilp_ver.get("part_b_edge_cases") or {}
        e5_s15 = (e2e_step(e2e5, 15) or {}).get("details") or {}
        e5_s16 = (e2e_step(e2e5, 16) or {}).get("details") or {}
        mo_ok = (
            pa15.get("bnb_exact_matches") == 1500
            and pa15.get("highs_exact_matches") == 1500
            and pb14.get("passed") == 14
            and all((e2e_step(e2e5, k) or {}).get("passed") for k in (15, 16, 17, 18))
        )
        mo_status = "PASS" if mo_ok else "PARTIAL"
        mo_fact = (
            f"0-1 ILP решатель: {pa15.get('bnb_exact_matches')}/{pa15.get('trials')} (100 %) точных совпадений с полным перебором и HiGHS 1.16.0, "
            f"{pa15.get('min_required_budget_exact_matches')}/{pa15.get('min_required_budget_checked')} точных min_required_budget, "
            f"{pb14.get('passed')}/{pb14.get('total')} граничных случаев PASS. "
            f"В E2E прогоне 5 (шаги 15–18): status = {e5_s15.get('status')}, gap = {e5_s15.get('gap')}, выбрано {e5_s15.get('selected')} поз. на {e5_s16.get('total_capex_rub')} ₽ ≤ {e5_s16.get('budget_rub')} ₽, "
            f"обязательная PI-102 включена, все коды плана (включая основной прибор PI-107 после DEF-INT-14) сверены в MD и DOCX; "
            f"кривая Парето и сохранение плана работают в HMI на 3 разрешениях, общий time_limit_s соблюдается (DEF-INT-05 закрыт)"
        )
        mo_ev = "reports/next_generation/ILP_INDEPENDENT_VERIFICATION.md; reports/next_generation/evidence/ilp/ilp_verification_and_scalability.json; evidence/e2e/e2e_results_run5.json; evidence/hmi/hmi_results.json"
    else:
        mo_status, mo_fact, mo_ev = "NOT VERIFIED", "Нет доказательств Modernization Optimizer", "—"
    ng_rows.append({
        "ID": "NG-MO-01",
        "Компонент": "Modernization Optimizer (0-1 ILP)",
        "Ветка-источник": "next-gen/analytics-validation",
        "Критерий приёмки": "Точный 0-1 ILP по бюджету с обязательными позициями и ограничениями, кривая Парето, интеграция в ТЗ и HMI, математическая верификация",
        "Статус": mo_status,
        "Фактический результат": mo_fact,
        "Доказательство": mo_ev,
        "Ограничения и дефекты": "Достоверность экономических ставок и паспортов — ответственность инженера; при нехватке time_limit_s точки Парето помечаются not_computed",
    })

    with open(OUT_NG, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ng_rows[0].keys()))
        w.writeheader()
        w.writerows(ng_rows)

    ng_counts = {k: sum(1 for r in ng_rows if r["Статус"] == k) for k in ("PASS", "PARTIAL", "FAILED", "NOT VERIFIED")}
    score = {
        "original_75": {
            "directions": dirs_score,
            "total": round(total_pts, 2),
            "total_exact": round(total_pts, 6),
            "counts": counts_75,
            "compliance_pct": round((counts_75["PASS"] + 0.5 * counts_75["PARTIAL"]) / 75 * 100, 1),
            "verified_pct": round((75 - counts_75["NOT VERIFIED"]) / 75 * 100, 1),
            "history": {
                "gemini_audit": 60.30,
                "gaugevision_2_0": 96.65,
                "scada_intermediate": 97.79,
                "gaugevision_3_0_cpu_final": round(total_pts, 2),
                "delta_vs_2_0": round(total_pts - 96.65, 2),
                "delta_vs_scada_intermediate": round(total_pts - 97.79, 2),
                "note_delta": "REQ-CV-05: NOT VERIFIED -> PARTIAL (+0,83); REQ-CV-06: PASS -> NOT VERIFIED (-1,67), т. к. app/vision.py изменён, а GPU в этой приёмке не проверялся",
            },
        },
        "next_gen_6": {
            "counts": ng_counts,
            "statuses": {r["ID"]: r["Статус"] for r in ng_rows},
        },
    }
    OUT_SCORE.write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "original_75_total": score["original_75"]["total"],
        "original_75_counts": counts_75,
        "compliance_pct": score["original_75"]["compliance_pct"],
        "verified_pct": score["original_75"]["verified_pct"],
        "next_gen_statuses": score["next_gen_6"]["statuses"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
