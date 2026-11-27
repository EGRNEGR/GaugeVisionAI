"""
Независимые приёмочные тесты повторной инженерной приёмки GaugeVision AI.

Написаны отдельно от тестов предыдущего этапа и проверяют архитектурные гарантии
по исходным критериям аудита (reports/audit/DEFECT_REGISTER.md) и ТЗ, а не текущее
поведение кода. Компенсируют ослабленные проверки test_remediation_full.py
(SHA-256 кадра, идентичность клипов кольцевого буфера) и покрывают дефекты,
найденные при повторной приёмке (NEW-01…NEW-13).

Запуск (строго CPU):
  CUDA_VISIBLE_DEVICES="" GAUGEVISION_DEVICE=cpu python -B tests/test_acceptance_independent.py
Результат в JSON: переменная ACCEPTANCE_TEST_OUT=<путь>.
Дочерние режимы (вызываются самим тестом в отдельном процессе):
  --production-child  — запуск вне деморежима (стендовые пароли запрещены);
  --migration-child   — открытие БД исходной схемы baseline dd25bde.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as _dt
import hashlib
import io
import json
import logging
import math
import os
import random
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODE = sys.argv[1] if len(sys.argv) > 1 else "main"
_TMP = Path(tempfile.mkdtemp(prefix=f"gv_accept_{MODE.strip('-')}_"))

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"
os.environ["GAUGEVISION_DB"] = str(_TMP / "main.db")
os.environ["GAUGEVISION_SF_DB"] = str(_TMP / "sf.db")
os.environ["GAUGEVISION_INCIDENTS_DIR"] = str(_TMP / "incidents")
os.environ["GAUGEVISION_AUTO_SPECS_DIR"] = str(_TMP / "auto_specs")
os.environ["GAUGEVISION_VIDEOS_DIR"] = str(_TMP / "videos")
os.environ["YOLO_CONFIG_DIR"] = str(_TMP / "yolo_cfg")
os.environ["GAUGEVISION_AUTH_REQUIRED"] = "1"
os.environ["GAUGEVISION_WS_SESSION_RECHECK"] = "0.5"
os.environ["GAUGEVISION_MODBUS_ENABLED"] = "0"
os.environ["GAUGEVISION_MQTT_ENABLED"] = "0"
os.environ["GAUGEVISION_DEMO"] = "0" if MODE == "--production-child" else "1"
for _k in ("GAUGEVISION_ADMIN_PASS", "GAUGEVISION_ENGINEER_PASS", "GAUGEVISION_OPERATOR_PASS",
           "GAUGEVISION_ALLOW_LOOPBACK_STREAMS", "GAUGEVISION_ALLOW_EXTERNAL_STREAMS",
           "GAUGEVISION_ALLOWED_STREAM_CIDRS", "GAUGEVISION_LLM_BASE_URL"):
    os.environ.pop(_k, None)

RESULTS: list[dict[str, Any]] = []


def case(name: str, refs: str) -> Callable[[Callable[[], Any]], Callable[[], Any]]:
    def deco(fn: Callable[[], Any]) -> Callable[[], Any]:
        def run() -> None:
            t0 = time.perf_counter()
            try:
                details = fn()
                if asyncio.iscoroutine(details):
                    details = asyncio.run(details)
                RESULTS.append({"name": name, "refs": refs, "passed": True,
                                "ms": round((time.perf_counter() - t0) * 1000, 1), "details": details})
                print(f"[PASS] {name} ({refs})")
            except Exception as exc:  # фиксируем и продолжаем остальные проверки
                RESULTS.append({"name": name, "refs": refs, "passed": False,
                                "ms": round((time.perf_counter() - t0) * 1000, 1),
                                "error": f"{type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc()[-2500:]})
                print(f"[FAIL] {name} ({refs}): {type(exc).__name__}: {exc}")
        run.__name__ = fn.__name__
        return run
    return deco


# ===========================================================================
# 1. Диспетчерская аналитика: математика и устойчивость к частоте опроса
# ===========================================================================
class _Clock:
    def __init__(self, t0: float) -> None:
        self.t = t0

    def __call__(self) -> float:
        return self.t


def _inst(value: float | None, level: str = "normal", *, conf: float = 0.9, iid: str = "cam1",
          gauge_type: str = "pressure", source_kind: str = "phone_cv") -> dict[str, Any]:
    return {
        "id": iid, "code": "К1-Р01", "name": "Манометр", "short_name": "Манометр", "group": "Котлоагрегаты",
        "gauge_type": gauge_type, "unit": "МПа", "decimals": 2, "source_kind": source_kind,
        "calibration": {"v_min": 0.0, "v_max": 16.0},
        "thresholds": {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2},
        "reading": {"valid": value is not None, "value": value, "level": level, "confidence": conf},
    }


@case("dispatch_noise_under_hmi_polling", "NEW-01, DEF-14, REQ-DA-02")
def t_dispatch_polling() -> dict[str, Any]:
    from app import dispatch_analyzer as da_mod
    from app.dispatch_analyzer import DispatchAnalyzer

    rnd = random.Random(7)
    clock = _Clock(1_800_000_000.0)
    orig = da_mod.time.time
    da_mod.time.time = clock  # type: ignore[assignment]
    try:
        da = DispatchAnalyzer()
        last = None
        # 30 с опроса HMI с частотой 20 Гц, исправный прибор 12,0 ± 0,02 МПа
        for _ in range(600):
            clock.t += 0.05
            last = da.overview([_inst(12.0 + rnd.uniform(-0.02, 0.02))], [], {})["instruments"][0]
        assert last is not None
        assert last["hydraulic_shock_risk"] is False, last
        assert last["root_cause"] == "nominal", last["root_cause"]
        assert last["modernization_needed"] is False
        assert last["health_score"] >= 90.0, last["health_score"]
        noisy = {"peak_rate_per_min": last["peak_rate_per_min"], "health": last["health_score"]}

        # Чувствительность сохранена: реальный скачок 12 → 16 МПа за 2 с — гидроудар
        da2 = DispatchAnalyzer()
        for v in (12.0, 12.0, 12.0, 15.9):
            clock.t += 2.0
            r2 = da2.overview([_inst(v, "alert" if v > 15.2 else "normal")], [], {})["instruments"][0]
        assert r2["hydraulic_shock_risk"] is True, r2
        assert r2["root_cause"] == "process_anomaly"
        assert abs(r2["peak_rate_per_min"] - (3.9 / (2.0 / 60.0))) < 0.5, r2["peak_rate_per_min"]
        return {"stable_20hz": noisy, "real_jump_peak_rate": r2["peak_rate_per_min"]}
    finally:
        da_mod.time.time = orig  # type: ignore[assignment]


@case("dispatch_overload_trips_and_health_split", "DEF-08, REQ-DA-04/05/07/08, REQ-ARCH-03")
def t_dispatch_math() -> dict[str, Any]:
    from app import dispatch_analyzer as da_mod
    from app.dispatch_analyzer import DispatchAnalyzer

    clock = _Clock(1_800_000_000.0)
    orig = da_mod.time.time
    da_mod.time.time = clock  # type: ignore[assignment]
    try:
        # Перегрузка: первый тик в аварии не добавляет времени (без фантомных +6,5 мин);
        # затем 90 тиков по 2 с — ровно 3,0 мин
        da = DispatchAnalyzer()
        r = da.overview([_inst(15.6, "alert")], [], {})["instruments"][0]
        assert r["overload_min"] == 0.0, r["overload_min"]
        for _ in range(90):
            clock.t += 2.0
            r = da.overview([_inst(15.6, "alert")], [], {})["instruments"][0]
        assert abs(r["overload_min"] - 3.0) < 0.01, r["overload_min"]

        # Срабатывания по реальным окнам 12 ч / 24 ч
        def ev(hours_ago: float, eid: int) -> dict[str, Any]:
            ts = _dt.datetime.fromtimestamp(clock.t - hours_ago * 3600, tz=_dt.timezone.utc).isoformat()
            return {"id": eid, "kind": "alarm", "cam_id": "cam1", "level": "warning", "ts": ts}
        evs = [ev(2, 1), ev(11.5, 2), ev(13, 3), ev(23, 4), ev(30, 5), ev(100, 6)]
        r = DispatchAnalyzer().analyze_instrument(_inst(12.0), evs, None, now_unix=clock.t)
        assert (r["trips_shift"], r["trips_24h"]) == (2, 4), (r["trips_shift"], r["trips_24h"])

        # Деградация камеры снижает optical_health, но не техсостояние исправного узла
        clean = DispatchAnalyzer().analyze_instrument(_inst(12.0, conf=0.95), [], None, now_unix=clock.t)
        fog_tel = {"health_status": "DEGRADED", "quality": {"quality_score": 40.0, "steam_occlusion": True,
                                                           "degradation_reasons": ["пар"], "updated_at": "x"}}
        fog = DispatchAnalyzer().analyze_instrument(_inst(12.0, conf=0.20), [], fog_tel, now_unix=clock.t)
        assert fog["optical_health"] <= 40.0, fog["optical_health"]
        assert fog["equipment_health"] == clean["equipment_health"] == 100.0, (fog["equipment_health"], clean["equipment_health"])
        assert fog["health_score"] == clean["health_score"], (fog["health_score"], clean["health_score"])
        assert fog["root_cause"] == "optical_degradation" and fog["modernization_needed"] is False
        return {"overload_min_90x2s": r["overload_min"] if "overload_min" in r else None,
                "fog_optical": fog["optical_health"], "fog_health": fog["health_score"]}
    finally:
        da_mod.time.time = orig  # type: ignore[assignment]


# ===========================================================================
# 2. Статистика периода в SQLite против независимого расчёта
# ===========================================================================
def _brute_stats(rows: list[tuple[str, float, float, str]]) -> dict[str, dict[str, Any]]:
    """rows: (cid, t_unix, value, level) — эталонный расчёт без SQL."""
    out: dict[str, dict[str, Any]] = {}
    by: dict[str, list[tuple[float, float, str]]] = {}
    for cid, t, v, lv in rows:
        by.setdefault(cid, []).append((t, v, lv))
    for cid, pts in by.items():
        pts.sort(key=lambda p: p[0])
        overload = 0.0
        peak_rate = 0.0
        for (t0, v0, l0), (t1, v1, _l1) in zip(pts, pts[1:]):
            dt = t1 - t0
            if 1e-3 < dt <= 600.0:
                if l0 in ("warning", "alert"):
                    overload += dt
                peak_rate = max(peak_rate, abs(v1 - v0) / (dt / 60.0))
        vals = [p[1] for p in pts]
        out[cid] = {"n": len(pts), "min": min(vals), "max": max(vals), "avg": sum(vals) / len(vals),
                    "overload_min": overload / 60.0, "peak_rate": peak_rate,
                    "cov_min": (pts[-1][0] - pts[0][0]) / 60.0}
    return out


@case("period_stats_sql_vs_reference", "NEW-05, NEW-06, DEF-03, REQ-DOC-04")
async def t_period_stats() -> dict[str, Any]:
    from app import db

    await db.init_db()
    await db.create_camera(name="Камера-эталон", type="rtsp", source_url="rtsp://192.168.10.5/s", cam_id="ref-cam")
    rnd = random.Random(11)
    now = _dt.datetime.now(_dt.timezone.utc)
    t_end = now.timestamp() - 30.0
    ref_rows: list[tuple[str, float, float, str]] = []
    cam_rows, inst_rows = [], []
    for cid, n, step in (("ref-cam", 900, 1.0), ("sim-99", 400, 5.0)):
        t = t_end - n * step * 1.6 - 2000.0  # с запасом на разрывы: все точки строго в прошлом
        for i in range(n):
            t += step * rnd.uniform(0.5, 1.5)
            if i in (120, 300):
                t += 900.0  # разрыв связи 15 мин: не засчитывается в перегрузку
            v = round(10.0 + 4.0 * math.sin(i / 40.0) + rnd.uniform(-0.05, 0.05), 4)
            lv = "alert" if v > 13.6 else ("warning" if v > 13.0 else "normal")
            ts = _dt.datetime.fromtimestamp(t, tz=_dt.timezone.utc).isoformat(timespec="milliseconds")
            ref_rows.append((cid, t, v, lv))
            if cid == "ref-cam":
                cam_rows.append((cid, ts, v, 0.0, lv, "МПа", None))
            else:
                inst_rows.append((cid, "simulated", ts, v, lv, "МПа"))
    await db.insert_readings(cam_rows)
    await db.insert_instrument_readings(inst_rows)
    since = (now - _dt.timedelta(days=2)).isoformat(timespec="milliseconds")
    t0 = time.perf_counter()
    got = await db.get_period_reading_stats(since, now.isoformat(timespec="milliseconds"))
    sql_ms = (time.perf_counter() - t0) * 1000
    exp = _brute_stats(ref_rows)
    for cid, e in exp.items():
        g = got[cid]
        assert g["samples_count"] == e["n"], (cid, g["samples_count"], e["n"])
        assert abs(g["min_val"] - e["min"]) < 1e-3 and abs(g["max_val"] - e["max"]) < 1e-3
        assert abs(g["avg_val"] - e["avg"]) < 1e-3
        assert abs(g["overload_min"] - e["overload_min"]) < 0.02, (cid, g["overload_min"], e["overload_min"])
        assert abs(g["peak_rate_per_min"] - e["peak_rate"]) / max(1.0, e["peak_rate"]) < 0.01, (cid, g["peak_rate_per_min"], e["peak_rate"])
        assert abs(g["coverage_min"] - e["cov_min"]) < 0.05
    # Фильтр по идентификаторам распространяется на обе таблицы
    only = await db.get_period_reading_stats(since, None, ["sim-99"])
    assert set(only) == {"sim-99"}
    return {"rows": len(ref_rows), "sql_ms": round(sql_ms, 1),
            "ref_cam_overload_min": got["ref-cam"]["overload_min"], "sim_peak_rate": got["sim-99"]["peak_rate_per_min"]}


# ===========================================================================
# 3. Store-and-Forward: кадр, дубли, рост БД, отказ брокера
# ===========================================================================
@case("store_forward_frames_duplicates_growth", "DEF-01, DEF-06, DEF-21, NEW-02, NEW-03, REQ-SF-05/06/11/12")
async def t_store_forward() -> dict[str, Any]:
    from app import config
    from app.scada_gateway import ScadaGateway
    from app.store_forward import StoreAndForwardBuffer

    sf = StoreAndForwardBuffer(db_path=_TMP / "sf_accept.db")
    delivered: list[dict[str, Any]] = []

    async def sink(items: list[dict[str, Any]]) -> bool:
        await asyncio.sleep(0.002)
        for it in items:
            blob = it.get("frame_blob")
            if blob is not None:
                assert hashlib.sha256(blob).hexdigest() == it["frame_sha256"], "SHA-256 кадра не совпал"
            delivered.append({"uuid": it["event_uuid"], "seq": it["seq_id"], "has_blob": blob is not None,
                              "blob_sha": hashlib.sha256(blob).hexdigest() if blob else None})
        return True

    sf.configure(deliver_cb=sink)
    await sf.init()
    frame = os.urandom(48_000)
    sha = hashlib.sha256(frame).hexdigest()

    # (а) обрыв: кадр копится на диске; после восстановления доставляется байт-в-байт
    await sf.set_outage(True, "accept")
    r_alarm = await sf.enqueue(channel_id="c1", payload_type="alarm", severity="alert",
                               payload={"v": 15.9}, frame_blob=frame)
    assert r_alarm["status"] == "pending"
    con = sqlite3.connect(_TMP / "sf_accept.db")
    stored_sha = con.execute("SELECT frame_sha256 FROM sf_queue WHERE seq_id=?", (r_alarm["seq_id"],)).fetchone()[0]
    assert stored_sha == sha, "SHA-256 кадра при постановке в очередь"
    sf._outage_active = False
    await sf.flush_pending(max_batches=5)
    got = [d for d in delivered if d["uuid"] == r_alarm["event_uuid"]]
    assert len(got) == 1 and got[0]["has_blob"] and got[0]["blob_sha"] == sha
    # после подтверждения байты кадра не хранятся, SHA и размер остаются
    blob_after, sha_after = con.execute("SELECT frame_blob, frame_sha256 FROM sf_queue WHERE seq_id=?",
                                        (r_alarm["seq_id"],)).fetchone()
    assert blob_after is None and sha_after == sha

    # (б) конкурентная запись и досылка: каждая запись доставлена ровно один раз
    delivered.clear()
    await sf.set_outage(True, "backlog")
    for i in range(60):
        await sf.enqueue(channel_id="c1", payload_type="telemetry", payload={"i": i})
    sf._outage_active = False

    async def producer() -> None:
        for i in range(120):
            await sf.enqueue(channel_id="c2", payload_type="telemetry", payload={"j": i})
            await asyncio.sleep(0)

    await asyncio.gather(producer(), sf.flush_pending(max_batches=20), sf.flush_pending(max_batches=20))
    for _ in range(10):
        await sf.flush_pending(max_batches=20)
    uuids = [d["uuid"] for d in delivered]
    dup = len(uuids) - len(set(uuids))
    pending = await sf.pending_count()
    assert dup == 0, f"дубликаты доставки: {dup}"
    assert pending == 0 and len(set(uuids)) == 180, (pending, len(set(uuids)))
    seqs_c1 = [d["seq"] for d in delivered]
    assert seqs_c1 == sorted(seqs_c1), "нарушен хронологический порядок seq_id"
    con.close()

    # (в) рост БД: 400 доставленных тревог с кадрами 48 КБ не накапливают байты кадров
    for _ in range(400):
        await sf.enqueue(channel_id="c3", payload_type="alarm", severity="alert", payload={}, frame_blob=frame)
    con = sqlite3.connect(_TMP / "sf_accept.db")
    blob_bytes = con.execute("SELECT COALESCE(SUM(LENGTH(frame_blob)),0) FROM sf_queue WHERE status='sent'").fetchone()[0]
    con.close()
    assert blob_bytes == 0, f"в доставленных записях хранится {blob_bytes} байт кадров"

    # (г) реальный отказ брокера: MQTT включён, порт закрыт — записи остаются pending
    free_port = socket.socket()
    free_port.bind(("127.0.0.1", 0))
    port = free_port.getsockname()[1]
    free_port.close()
    saved = (config.MQTT_ENABLED, config.MQTT_PORT, config.MQTT_HOST, config.MQTT_ACK_TIMEOUT)
    config.MQTT_ENABLED, config.MQTT_PORT, config.MQTT_HOST, config.MQTT_ACK_TIMEOUT = True, port, "127.0.0.1", 0.5
    try:
        sf2 = StoreAndForwardBuffer(db_path=_TMP / "sf_broker_down.db")
        gw = ScadaGateway()
        sf2.configure(deliver_cb=gw.deliver_batch)
        res = await sf2.enqueue(channel_id="c1", payload_type="alarm", severity="alert", payload={"v": 15.9},
                                frame_blob=frame)
        assert res["status"] == "pending", res
        assert await sf2.pending_count() == 1
        st = gw.status()["mqtt"]
        assert st["publish_failures"] >= 1 and st["broker_sent"] == 0
        await sf2.close()
    finally:
        config.MQTT_ENABLED, config.MQTT_PORT, config.MQTT_HOST, config.MQTT_ACK_TIMEOUT = saved
    await sf.close()
    return {"duplicates": dup, "delivered_unique": len(set(uuids)), "sent_blob_bytes": blob_bytes,
            "broker_down_status": res["status"]}


@case("store_forward_overflow_keeps_alarms", "DEF-06, REQ-SF-12")
async def t_sf_overflow() -> dict[str, Any]:
    from app import config
    from app.store_forward import StoreAndForwardBuffer

    saved = config.SF_MAX_QUEUE_ROWS
    config.SF_MAX_QUEUE_ROWS = 40
    try:
        sf = StoreAndForwardBuffer(db_path=_TMP / "sf_overflow.db")
        await sf.init()
        await sf.set_outage(True, "overflow")
        for i in range(30):
            await sf.enqueue(channel_id="t", payload_type="telemetry", payload={"i": i})
        alarm_ids = []
        for i in range(10):
            r = await sf.enqueue(channel_id="a", payload_type="alarm", severity="alert", payload={"k": i})
            alarm_ids.append(r["seq_id"])
        for i in range(30):
            await sf.enqueue(channel_id="t", payload_type="telemetry", payload={"i": 100 + i})
        st = await sf.stats()
        assert st["pending_count"] <= 40, st["pending_count"]
        assert st["queue_overflow"] is True and st["evicted_total"] >= 20
        con = sqlite3.connect(_TMP / "sf_overflow.db")
        kept = {r[0] for r in con.execute("SELECT seq_id FROM sf_queue WHERE payload_type='alarm'")}
        logged = con.execute("SELECT COUNT(*) FROM sf_overflow_log").fetchone()[0]
        con.close()
        assert set(alarm_ids) <= kept, "вытеснена тревога"
        assert logged >= 1
        await sf.close()
        return {"pending": st["pending_count"], "evicted": st["evicted_total"], "alarms_kept": len(kept)}
    finally:
        config.SF_MAX_QUEUE_ROWS = saved


@case("store_forward_real_link_failure_reported", "NEW-12, REQ-SF-06")
async def t_sf_link_state() -> dict[str, Any]:
    from app.store_forward import StoreAndForwardBuffer

    link = {"up": False}
    got: list[str] = []

    async def sink(items: list[dict[str, Any]]) -> bool:
        if not link["up"]:
            return False
        got.extend(it["event_uuid"] for it in items)
        return True

    sf = StoreAndForwardBuffer(db_path=_TMP / "sf_link.db")
    sf.configure(deliver_cb=sink)
    await sf.init()
    st0 = await sf.stats()
    assert st0["sync_state"] == "CONNECTED" and st0["link_down"] is False, st0["sync_state"]
    # брокер недоступен без симуляции обрыва: доставка не подтверждается
    uuids = [(await sf.enqueue(channel_id="c", payload_type="telemetry", payload={"i": i}))["event_uuid"]
             for i in range(5)]
    st1 = await sf.stats()
    assert st1["outage_active"] is False
    assert st1["link_down"] is True and st1["sync_state"] == "BUFFERING", (st1["sync_state"], st1["link_down"])
    assert st1["pending_count"] == 5 and st1["delivery_fail_streak"] >= 1
    # канал восстановлен: очередь досылается, состояние возвращается в CONNECTED
    link["up"] = True
    sf._retry_backoff_until = 0.0
    await sf.flush_pending(max_batches=5)
    st2 = await sf.stats()
    assert st2["pending_count"] == 0 and st2["link_down"] is False and st2["sync_state"] == "CONNECTED"
    assert set(uuids) <= set(got)
    # симуляция обрыва из пульта по-прежнему даёт BUFFERING, но не link_down
    await sf.set_outage(True, "accept")
    await sf.enqueue(channel_id="c", payload_type="telemetry", payload={"i": 99})
    st3 = await sf.stats()
    assert st3["sync_state"] == "BUFFERING" and st3["outage_active"] is True and st3["link_down"] is False
    await sf.close()
    return {"failing": {"sync_state": st1["sync_state"], "pending": st1["pending_count"],
                        "fail_streak": st1["delivery_fail_streak"]},
            "recovered": st2["sync_state"], "simulated_outage": st3["sync_state"]}


@case("llm_reasoning_model_empty_content_handled", "NEW-13, REQ-DOC-10")
async def t_llm_reasoning() -> dict[str, Any]:
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from app import config
    from app.spec_generator import _try_llm_enrichment

    seen: list[dict[str, Any]] = []
    mode = {"m": "empty"}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            if mode["m"] == "strict" and "reasoning_effort" in body:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error":"unknown field reasoning_effort"}')
                return
            content = {"empty": "", "think": "<think>скрытое рассуждение 99,9</think>Итоговое резюме.",
                       "strict": "Ответ строгого сервера."}[mode["m"]]
            msg = {"role": "assistant", "content": content}
            if mode["m"] == "empty":
                msg["reasoning"] = "длинное рассуждение " * 50
            out = json.dumps({"choices": [{"message": msg, "finish_reason": "length" if mode["m"] == "empty" else "stop"}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out.encode("utf-8"))

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    saved = (config.LLM_BASE_URL, config.LLM_DISABLE_REASONING)
    config.LLM_BASE_URL = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    config.LLM_DISABLE_REASONING = True
    try:
        # (а) рассуждающая модель исчерпала лимит: откат с честной причиной, не «недоступна»
        t1, e1 = await _try_llm_enrichment("факты")
        assert t1 is None and e1.startswith("deterministic") and "fallback" in e1 and "пустой ответ" in e1, e1
        assert seen[-1].get("reasoning_effort") == "none" and seen[-1]["max_tokens"] == config.LLM_MAX_TOKENS
        # (б) блок <think> в content не попадает в документ
        mode["m"] = "think"
        t2, e2 = await _try_llm_enrichment("факты")
        assert e2.startswith("llm_enhanced") and t2 == "Итоговое резюме.", (e2, t2)
        # (в) сервер без поддержки reasoning_effort: повтор без параметра
        mode["m"] = "strict"
        n0 = len(seen)
        t3, e3 = await _try_llm_enrichment("факты")
        assert e3.startswith("llm_enhanced") and t3 == "Ответ строгого сервера."
        assert len(seen) - n0 == 2 and "reasoning_effort" not in seen[-1]
        return {"empty_reason": e1, "think_stripped": t2, "strict_retry_requests": len(seen) - n0}
    finally:
        config.LLM_BASE_URL, config.LLM_DISABLE_REASONING = saved
        srv.shutdown()


# ===========================================================================
# 4. Кольцевой буфер инцидентов
# ===========================================================================
@case("ring_buffer_concurrent_clip_identity", "DEF-10, NEW-08, REQ-VA-10")
def t_ring() -> dict[str, Any]:
    from app.stream_manager import IncidentRingBuffer

    d = _TMP / "ring"
    rb = IncidentRingBuffer(pre_len=5, post_len=4, max_archives=10, max_active=2, storage_dir=d)
    frames = [f"frame-{i}".encode() for i in range(40)]
    k = 0
    for _ in range(5):
        rb.push(frames[k]); k += 1
    c1 = rb.trigger("A", "alert", 15.5)["clip_id"]
    rb.push(frames[k]); k += 1
    c2 = rb.trigger("B", "alert", 15.9)["clip_id"]
    rb.push(frames[k]); k += 1
    c3 = rb.trigger("C", "warning", 14.5)["clip_id"]  # превышен max_active=2 → c1 завершается досрочно
    for _ in range(6):
        rb.push(frames[k]); k += 1
    metas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in d.glob("clip_*.json")}
    assert {c1, c2, c3} <= set(metas), f"сохранены не все клипы: {sorted(metas)}"
    m1, m2 = metas[c1], metas[c2]
    # pre-кадры строго до триггера: у c1 — кадры 0..4, у c2 — 1..5
    pre1 = [(d / f).read_bytes() for f in m1["pre_files"]]
    pre2 = [(d / f).read_bytes() for f in m2["pre_files"]]
    assert pre1 == frames[0:5] and pre2 == frames[1:6], (pre1, pre2)
    post2 = [(d / f).read_bytes() for f in m2["post_files"]]
    assert post2 == frames[6:10], post2
    rb2 = IncidentRingBuffer(pre_len=5, post_len=4, max_archives=10, storage_dir=d)
    restored = {a["clip_id"] for a in rb2._archives}
    assert {c1, c2, c3} <= restored, restored
    return {"clips": sorted(metas), "c1_post_count": m1["post_count"]}


# ===========================================================================
# 5. Генератор ТЗ: честность ведомости и CAPEX
# ===========================================================================
def _disp_item(iid: str, *, health: float = 100.0, root: str = "nominal", level: str = "normal",
               modernization: bool = False) -> dict[str, Any]:
    from app.dispatch_analyzer import ROOT_CAUSE_META

    return {
        "id": iid, "code": iid.upper(), "short_name": iid, "name": iid, "group": "Котлоагрегаты",
        "gauge_type": "pressure", "unit": "МПа", "decimals": 2, "source_kind": "simulated",
        "value": 12.0, "level": level, "valid": True,
        "thresholds": {"h_warn": 14.2, "hh_alert": 15.2}, "calibration": {"v_min": 0, "v_max": 16},
        "health_score": health, "equipment_health": health, "instrument_health": 100.0,
        "optical_health": 95.0, "communication_health": 100.0, "root_cause": root,
        "root_cause_meta": ROOT_CAUSE_META[root], "recommendation": "—", "modernization_needed": modernization,
        "rate_symbol": "dP/dt", "rate_per_min": 0.0, "peak_rate_per_min": 0.0, "chatter_pct": 0.0,
        "overload_min": 0.0, "trips_shift": 0, "trips_24h": 0, "critical_wear": False,
    }


@case("spec_single_trip_vs_regular_overloads", "DEF-04, REQ-DOC-06/08")
async def t_spec_trips() -> dict[str, Any]:
    from app.spec_generator import generate_spec_bundle

    now = _dt.datetime.now(_dt.timezone.utc)

    def trip(eid: int, hours_ago: float) -> dict[str, Any]:
        return {"id": eid, "kind": "alarm", "cam_id": "p1", "level": "warning",
                "ts": (now - _dt.timedelta(hours=hours_ago)).isoformat()}

    ov = {"instruments": [_disp_item("p1"), _disp_item("p2")]}
    healthy = await generate_spec_bundle(dispatch_overview=ov, events=[], snapshot_lookup={}, period="24h", now_utc=now)
    assert not healthy["defective_items"] and not healthy["tz_items"]
    assert healthy["economics"]["capex_rub"] == 0 and healthy["economics"]["payback_months"] is None

    one = await generate_spec_bundle(dispatch_overview=ov, events=[trip(1, 3)], snapshot_lookup={}, period="24h", now_utc=now)
    assert [x["id"] for x in one["defective_items"]] == ["p1"], "единичное срабатывание фиксируется в ведомости"
    assert not one["tz_items"] and one["economics"]["capex_rub"] == 0, "единичное срабатывание не даёт CAPEX"

    reg = await generate_spec_bundle(dispatch_overview=ov, events=[trip(i, i) for i in range(1, 5)],
                                     snapshot_lookup={}, period="24h", now_utc=now)
    assert [r["item"]["id"] for r in reg["tz_items"]] == ["p1"]
    eco = reg["economics"]
    exp_capex = eco["hw_rub"] + eco["smr_rub"] + round((eco["hw_rub"] + eco["smr_rub"]) * eco["commissioning_rate"])
    assert eco["capex_rub"] == exp_capex
    assert eco["annual_effect_rub"] == max(0, eco["gross_annual_effect_rub"] - eco["opex_rub_yr"])
    assert eco["payback_months"] == max(1, round(eco["capex_rub"] / eco["annual_effect_rub"] * 12))

    # Период: срабатывание 30 ч назад не учитывается в 24h, но учитывается в 7d
    old = [trip(10, 30), trip(11, 40), trip(12, 50)]
    b24 = await generate_spec_bundle(dispatch_overview=ov, events=old, snapshot_lookup={}, period="24h", now_utc=now)
    b7d = await generate_spec_bundle(dispatch_overview=ov, events=old, snapshot_lookup={}, period="7d", now_utc=now)
    assert b24["period_events_count"] == 0 and b7d["period_events_count"] == 3
    assert not b24["tz_items"] and len(b7d["tz_items"]) == 1
    return {"single_trip_capex": one["economics"]["capex_rub"], "regular_capex": eco["capex_rub"],
            "payback_months": eco["payback_months"]}


# ===========================================================================
# 6. API: RBAC, сессии, SSRF, Path Traversal, NaN, утечки, период ТЗ, автогенерация
# ===========================================================================
def _api_checks() -> None:
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from app import auth, config, db
    from app import main as app_main

    log_buf = io.StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)

    SECRET = "S3cr3t-Pw-0rd-9917"

    with TestClient(app_main.app) as client:
        def login(user: str, pwd: str) -> str:
            r = client.post("/api/auth/login", json={"username": user, "password": pwd})
            assert r.status_code == 200, (user, r.status_code, r.text)
            return r.json()["token"]

        def hdr(tok: str) -> dict[str, str]:
            return {"Authorization": f"Bearer {tok}"}

        client.cookies.clear()
        adm = login("admin", config.ADMIN_PASSWORD)
        eng = login("engineer", config.ENGINEER_PASSWORD)
        op = login("operator", config.OPERATOR_PASSWORD)
        client.cookies.clear()

        @case("api_unauthenticated_and_meta", "DEF-07, NEW-04, REQ-SEC-05")
        def t_unauth() -> dict[str, Any]:
            codes = {p: client.get(p).status_code for p in (
                "/api/cameras", "/api/instruments", "/api/events", "/api/dispatch/overview",
                "/api/architecture/status", "/api/specs/auto", "/api/scada/modbus/registers")}
            assert all(c == 401 for c in codes.values()), codes
            meta = client.get("/api/meta").json()
            assert meta["authenticated"] is False
            for k in ("db_path", "lan_ip", "urls", "demo", "simulator_url", "cert_sha256"):
                assert k not in meta, f"/api/meta до входа раскрывает {k}"
            try:
                with client.websocket_connect("/ws/dashboard") as ws:
                    ws.receive_text()
                raise AssertionError("WebSocket без сессии принят")
            except WebSocketDisconnect as exc:
                assert exc.code == 4401
            h = client.get("/api/meta")
            assert h.headers.get("x-frame-options") == "DENY" and "frame-ancestors 'none'" in h.headers.get("content-security-policy", "")
            return {"unauth_codes": codes}

        @case("api_rbac_matrix", "DEF-07, REQ-SEC-05")
        def t_rbac() -> dict[str, Any]:
            matrix = [
                ("POST", "/api/cameras", {"name": "x", "type": "rtsp", "source_url": "rtsp://192.168.1.2/a"}, {"operator": 403, "engineer": 201}),
                ("POST", "/api/architecture/outage", {"active": False}, {"operator": 403, "engineer": 403, "admin": 200}),
                ("POST", "/api/architecture/degrade", {"stream_id": "edge-bench-k1t01", "mode": "none"}, {"operator": 403, "engineer": 403, "admin": 200}),
                ("GET", "/api/discover", None, {"operator": 403, "engineer": 403}),
                ("GET", "/api/auth/audit", None, {"operator": 403, "engineer": 403, "admin": 200}),
                ("POST", "/api/specs/preview", {"period": "12h"}, {"operator": 403, "engineer": 200}),
                ("POST", "/api/architecture/store-forward/flush", None, {"operator": 403, "engineer": 200}),
                ("GET", "/api/specs/auto", None, {"operator": 200}),
                ("GET", "/api/dispatch/overview", None, {"operator": 200}),
            ]
            toks = {"operator": op, "engineer": eng, "admin": adm}
            seen = {}
            for method, path, body, exp in matrix:
                for role, code in exp.items():
                    r = client.request(method, path, json=body, headers=hdr(toks[role]))
                    seen[f"{role} {method} {path}"] = r.status_code
                    assert r.status_code == code, (role, method, path, r.status_code, r.text[:200])
            # WebSocket оператору доступен
            with client.websocket_connect(f"/ws/dashboard?token={op}") as ws:
                first = json.loads(ws.receive_text())
                assert first["type"] == "snapshot"
            return seen

        @case("api_ssrf_and_path_traversal", "DEF-07, REQ-SEC-04")
        def t_ssrf() -> dict[str, Any]:
            bad_urls = [
                ("http_mjpeg", "http://169.254.169.254/latest/meta-data/"),
                ("http_mjpeg", "http://[::ffff:169.254.169.254]/"),
                ("http_mjpeg", "http://2852039166/"),
                ("http_mjpeg", "http://127.0.0.1:8443/api/meta"),
                ("http_mjpeg", "http://127.1/"),
                ("http_mjpeg", "http://localhost/"),
                ("http_mjpeg", "http://[::1]/"),
                ("http_mjpeg", "http://0.0.0.0/"),
                ("http_mjpeg", "http://metadata.google.internal/"),
                ("http_mjpeg", "http://8.8.8.8/stream"),
                ("http_mjpeg", "http://100.64.0.1/"),
                ("rtsp", "http://192.168.1.2/not-rtsp"),
                ("rtsp", "rtsp://[fe80::1]/live"),
            ]
            res = {}
            for typ, url in bad_urls:
                r = client.post("/api/cameras", json={"name": "ssrf", "type": typ, "source_url": url}, headers=hdr(eng))
                res[url] = r.status_code
                assert r.status_code == 422, (url, r.status_code, r.text[:200])
            vids = Path(os.environ["GAUGEVISION_VIDEOS_DIR"])
            vids.mkdir(parents=True, exist_ok=True)
            (vids / "bench.mp4").write_bytes(b"\x00" * 16)
            bad_paths = ["..\\..\\Windows\\win.ini", "../../etc/passwd", "C:\\Windows\\win.ini", "\\\\srv\\share\\a.mp4",
                         "Z:a.mp4", "sub/../../x.mp4", "bench.mp4\u0000.txt", "notes.txt", str(_TMP / "outside.mp4")]
            for pth in bad_paths:
                r = client.post("/api/cameras", json={"name": "pt", "type": "video_file", "source_url": pth}, headers=hdr(eng))
                res[pth] = r.status_code
                assert r.status_code == 422, (pth, r.status_code, r.text[:200])
            ok_abs = client.post("/api/cameras", json={"name": "ok", "type": "video_file", "source_url": str(vids / "bench.mp4")}, headers=hdr(eng))
            ok_rel = client.post("/api/cameras", json={"name": "ok2", "type": "video_file", "source_url": "bench.mp4"}, headers=hdr(eng))
            ok_lan = client.post("/api/cameras", json={"name": "lan", "type": "http_mjpeg", "source_url": "http://192.168.1.10/mjpg"}, headers=hdr(eng))
            assert ok_abs.status_code == ok_rel.status_code == ok_lan.status_code == 201, (ok_abs.text, ok_rel.text, ok_lan.text)
            assert ok_abs.json()["source_url"] == "bench.mp4"
            # путь относительно текущего каталога того же диска нормализуется внутрь data/videos
            same_drive = client.post("/api/cameras", json={"name": "dr", "type": "video_file", "source_url": "C:bench.mp4"}, headers=hdr(eng))
            if same_drive.status_code == 201:
                assert same_drive.json()["source_url"] == "bench.mp4", same_drive.json()["source_url"]
                client.delete(f"/api/cameras/{same_drive.json()['id']}", headers=hdr(adm))
            res["C:bench.mp4"] = same_drive.status_code
            for cid in (ok_abs.json()["id"], ok_rel.json()["id"], ok_lan.json()["id"]):
                client.delete(f"/api/cameras/{cid}", headers=hdr(adm))
            return res

        @case("api_rtsp_credentials_never_leak", "DEF-07, REQ-SEC-03")
        def t_leak() -> dict[str, Any]:
            url = f"rtsp://svc_user:{SECRET}@192.168.10.50:554/live"
            r = client.post("/api/cameras", json={"name": "IP-камера", "type": "rtsp", "source_url": url}, headers=hdr(eng))
            assert r.status_code == 201, r.text
            cid = r.json()["id"]
            bodies = [r.text]
            for p in ("/api/cameras", f"/api/cameras/{cid}", "/api/instruments", "/api/architecture/streams",
                      "/api/architecture/status", "/api/dispatch/overview", "/api/events"):
                bodies.append(client.get(p, headers=hdr(adm)).text)
            with client.websocket_connect(f"/ws/dashboard?token={adm}") as ws:
                bodies.append(ws.receive_text())
            assert all(SECRET not in b for b in bodies), "пароль RTSP в ответе API/WS"
            assert "***:***@192.168.10.50" in r.json()["source_url"]
            raw_db = b"".join(p.read_bytes() for p in Path(os.environ["GAUGEVISION_DB"]).parent.glob("main.db*"))
            assert SECRET.encode() not in raw_db, "пароль RTSP открытым текстом в SQLite"
            time.sleep(0.3)
            assert SECRET not in log_buf.getvalue(), "пароль RTSP в журнале"
            client.delete(f"/api/cameras/{cid}", headers=hdr(adm))
            return {"checked_responses": len(bodies)}

        @case("api_nan_payload_422", "DEF-09, REQ-API-02")
        def t_nan() -> dict[str, Any]:
            r = client.patch(f"/api/cameras/{config.DEMO_LIVE_CAM_ID}", content='{"thresholds": {"h_warn": NaN}}',
                             headers={**hdr(eng), "Content-Type": "application/json"})
            assert r.status_code == 422, (r.status_code, r.text[:200])
            json.loads(r.text)
            r2 = client.patch(f"/api/cameras/{config.DEMO_LIVE_CAM_ID}", content='{"calibration": {"v_min": Infinity, "v_max": 10}}',
                              headers={**hdr(eng), "Content-Type": "application/json"})
            assert r2.status_code == 422
            return {"nan": r.status_code, "inf": r2.status_code}

        @case("api_sessions_logout_role_change_ws", "NEW-04, REQ-SEC-05")
        def t_sessions() -> dict[str, Any]:
            tok = login("engineer", config.ENGINEER_PASSWORD)
            client.cookies.clear()
            assert client.get("/api/cameras", headers=hdr(tok)).status_code == 200
            # открытый поток закрывается после выхода из системы
            with client.websocket_connect(f"/ws/dashboard?token={tok}") as ws:
                assert json.loads(ws.receive_text())["type"] == "snapshot"
                client.post("/api/auth/logout", headers=hdr(tok))
                code = None
                t_end = time.time() + 8.0
                try:
                    while time.time() < t_end:
                        ws.receive_text()
                except WebSocketDisconnect as exc:
                    code = exc.code
            assert code == 4401, f"WS не закрыт после выхода (code={code})"
            assert client.get("/api/cameras", headers=hdr(tok)).status_code == 401
            # понижение роли и отключение учётной записи действуют сразу
            tok2 = login("engineer", config.ENGINEER_PASSWORD)
            client.cookies.clear()
            dbp = os.environ["GAUGEVISION_DB"]
            con = sqlite3.connect(dbp)
            con.execute("UPDATE users SET role='operator' WHERE username='engineer'")
            con.commit()
            demoted = client.post("/api/specs/preview", json={"period": "12h"}, headers=hdr(tok2)).status_code
            con.execute("UPDATE users SET active=0 WHERE username='engineer'")
            con.commit()
            disabled = client.get("/api/cameras", headers=hdr(tok2)).status_code
            con.execute("UPDATE users SET role='engineer', active=1 WHERE username='engineer'")
            con.commit()
            con.close()
            assert demoted == 403 and disabled == 401, (demoted, disabled)
            # подмена роли в токене невозможна: в БД хранится только SHA-256 токена
            con = sqlite3.connect(dbp)
            stored = [r[0] for r in con.execute("SELECT token_hash FROM sessions")]
            con.close()
            assert tok2 not in stored and hashlib.sha256(tok2.encode()).hexdigest() in stored
            return {"ws_close_code": code, "demoted": demoted, "disabled": disabled}

        @case("api_period_sensitivity_from_db", "DEF-03, NEW-06, REQ-DOC-04")
        def t_period_api() -> dict[str, Any]:
            cam = config.DEMO_LIVE_CAM_ID
            now = _dt.datetime.now(_dt.timezone.utc)
            pts = [(6, 7.71, "normal"), (20, 8.82, "normal"), (72, 9.93, "normal"), (480, 11.04, "normal")]
            rows = [(cam, (now - _dt.timedelta(hours=h)).isoformat(timespec="milliseconds"), v, 0.0, lv, "МПа", None)
                    for h, v, lv in pts]
            evs = [{"id": 900_000 + i, "ts": (now - _dt.timedelta(hours=h)).isoformat(timespec="milliseconds"),
                    "kind": "alarm", "cam_id": cam, "cam_name": "К1-Р01", "level": "warning",
                    "prev_level": "normal", "value": 14.5, "unit": "МПа", "text": ""}
                   for i, (h, _, _) in enumerate(pts)]

            async def seed() -> None:
                await db.insert_readings(rows)
                for e in evs:
                    await db.save_event(e)
            client.portal.call(seed)  # type: ignore[attr-defined]
            out = {}
            for per in ("12h", "24h", "7d", "30d"):
                r = client.post("/api/specs/preview", json={"period": per, "instrument_id": cam}, headers=hdr(eng))
                assert r.status_code == 200, r.text[:300]
                out[per] = r.json()
            samples = [out[p]["db_samples_count"] for p in ("12h", "24h", "7d", "30d")]
            events_n = [out[p]["period_events_count"] for p in ("12h", "24h", "7d", "30d")]
            assert [b - a for a, b in zip(samples, samples[1:])] == [1, 1, 1], samples
            assert [b - a for a, b in zip(events_n, events_n[1:])] == [1, 1, 1], events_n
            assert "11,04" in out["30d"]["markdown"] and "11,04" not in out["12h"]["markdown"]
            assert "7,71" in out["12h"]["markdown"]
            # Демо-телеметрия стендовых приборов пишется в SQLite и попадает в протокол
            client.portal.call(app_main.service._persist_simulated_readings)  # type: ignore[attr-defined]
            g = client.post("/api/specs/preview", json={"period": "12h", "group": "Турбоагрегаты"}, headers=hdr(eng)).json()
            assert g["db_samples_count"] > 0, g["db_samples_count"]
            return {"samples": samples, "events": events_n, "sim_group_samples": g["db_samples_count"]}

        @case("auto_spec_generation_lifecycle", "REQ-DA-09, DEF-20")
        def t_auto_spec() -> dict[str, Any]:
            svc = app_main.service
            # Фоновый цикл arch-sync сам создаёт автодокументы по деградирующим приборам демо-стенда;
            # на время проверки он останавливается, иначе проверка счёта триггеров зависит от гонки.
            sync_task = next(t for t in svc._bg if t.get_name() == "arch-sync")  # type: ignore[attr-defined]
            client.portal.call(_cancel_task, sync_task)
            # исходное состояние проверки: без автодокументов, созданных фоновым циклом до её начала
            client.portal.call(_clear_auto_specs, ("sim-12", "sim-02"))
            try:
                return _auto_spec_body(svc)
            finally:
                svc._bg.remove(sync_task)  # type: ignore[attr-defined]
                svc._bg.append(client.portal.call(_start_sync, svc))  # type: ignore[attr-defined]

        async def _cancel_task(task: Any) -> None:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task

        async def _clear_auto_specs(ids: tuple[str, ...]) -> None:
            async with db._lock:  # type: ignore[attr-defined]
                conn = await db._get_conn()  # type: ignore[attr-defined]
                await conn.execute(f"DELETE FROM auto_spec_triggers WHERE instrument_id IN ({','.join('?' * len(ids))})", ids)
                await conn.commit()

        async def _start_sync(svc: Any) -> Any:
            return asyncio.create_task(svc._architecture_sync_loop(), name="arch-sync")

        def _auto_spec_body(svc: Any) -> dict[str, Any]:
            disp = svc.dispatch.overview(svc.public_instruments(), svc.events.list(limit=300), svc.stream_telemetry_map())
            item = next(x for x in disp["instruments"] if x["id"] == "sim-12")
            forced = dict(item, critical_wear=True, health_score=31.0, root_cause="instrument_degradation")
            disp_one = {**disp, "instruments": [forced]}

            client.portal.call(svc._process_auto_spec_triggers, disp_one, [])  # type: ignore[attr-defined]
            trig = client.get("/api/specs/auto", headers=hdr(op)).json()
            mine = [t for t in trig if t["instrument_id"] == "sim-12"]
            assert len(mine) == 1 and mine[0]["status"] == "completed", mine
            t0 = mine[0]
            assert Path(t0["docx_path"]).is_file() and Path(t0["md_path"]).is_file()
            md = Path(t0["md_path"]).read_text(encoding="utf-8")
            assert forced["code"] in md and "Фактический охват БД SQLite" in md
            # повторный вызов и следующий временной бакет в пределах cooldown — без дубля
            client.portal.call(svc._process_auto_spec_triggers, disp_one, [])  # type: ignore[attr-defined]
            orig_time = app_main.time.time
            app_main.time.time = lambda: orig_time() + config.AUTO_SPEC_COOLDOWN_SECONDS  # type: ignore[assignment]
            try:
                client.portal.call(svc._process_auto_spec_triggers, disp_one, [])  # type: ignore[attr-defined]
            finally:
                app_main.time.time = orig_time  # type: ignore[assignment]
            again = [t for t in client.get("/api/specs/auto", headers=hdr(op)).json() if t["instrument_id"] == "sim-12"]
            assert len(again) == 1, f"дубль автодокумента: {len(again)}"
            # скачивание через HMI-маршрут оператором
            dl = client.get(f"/api/specs/auto/{t0['id']}/download?format=docx", headers=hdr(op))
            assert dl.status_code == 200
            with zipfile.ZipFile(io.BytesIO(dl.content)) as zf:
                xml = zf.read("word/document.xml").decode("utf-8")
            assert forced["code"] in xml
            # ошибка формирования фиксируется, затем повтор успешен
            item2 = next(x for x in disp["instruments"] if x["id"] == "sim-02")
            forced2 = dict(item2, critical_wear=True, health_score=28.0, root_cause="process_anomaly")
            orig_render = app_main.render_spec_docx

            def boom(_b: dict[str, Any]) -> bytes:
                raise RuntimeError("диск недоступен")
            app_main.render_spec_docx = boom  # type: ignore[assignment]
            try:
                client.portal.call(svc._process_auto_spec_triggers, {**disp, "instruments": [forced2]}, [])  # type: ignore[attr-defined]
            finally:
                app_main.render_spec_docx = orig_render  # type: ignore[assignment]
            failed = [t for t in client.get("/api/specs/auto", headers=hdr(op)).json() if t["instrument_id"] == "sim-02"]
            assert failed and failed[0]["status"] == "failed" and failed[0]["attempts"] == 1 and "диск" in (failed[0]["error"] or "")
            client.portal.call(svc._process_auto_spec_triggers, {**disp, "instruments": [forced2]}, [])  # type: ignore[attr-defined]
            fixed = [t for t in client.get("/api/specs/auto", headers=hdr(op)).json() if t["instrument_id"] == "sim-02"]
            assert fixed[0]["status"] == "completed" and fixed[0]["attempts"] == 2, fixed[0]
            return {"trigger_id": t0["id"], "docx_bytes": len(dl.content), "retry_attempts": fixed[0]["attempts"]}

        @case("api_login_bruteforce_lockout", "NEW-04, REQ-SEC-05")
        def t_lockout() -> dict[str, Any]:
            codes = [client.post("/api/auth/login", json={"username": "admin", "password": f"wrong-{i}"}).status_code
                     for i in range(config.LOGIN_MAX_FAILURES)]
            locked = client.post("/api/auth/login", json={"username": "admin", "password": config.ADMIN_PASSWORD})
            other = client.post("/api/auth/login", json={"username": "operator", "password": config.OPERATOR_PASSWORD})
            auth.reset_login_failures("admin", "testclient")
            client.cookies.clear()
            assert codes == [401] * config.LOGIN_MAX_FAILURES and locked.status_code == 429, (codes, locked.status_code)
            assert int(locked.headers.get("retry-after", "0")) > 0 and other.status_code == 200
            return {"failures": codes, "locked": locked.status_code}

        for fn in (t_unauth, t_rbac, t_ssrf, t_leak, t_nan, t_sessions, t_period_api, t_auto_spec, t_lockout):
            fn()

    # Перезапуск сервиса: автодокументы и журнал событий сохраняются
    @case("restart_persistence", "DEF-20, REQ-ARCH-04")
    def t_restart() -> dict[str, Any]:
        with TestClient(app_main.app) as client2:
            r = client2.post("/api/auth/login", json={"username": "operator", "password": config.OPERATOR_PASSWORD})
            tok = r.json()["token"]
            trig = client2.get("/api/specs/auto", headers={"Authorization": f"Bearer {tok}"}).json()
            evs = client2.get("/api/events?limit=1000", headers={"Authorization": f"Bearer {tok}"}).json()
            assert any(t["instrument_id"] == "sim-12" and t["status"] == "completed" for t in trig)
            ids = [e["id"] for e in evs]
            assert len(ids) == len(set(ids)), "повтор id событий после перезапуска"
            return {"auto_specs": len(trig), "events": len(evs)}
    t_restart()
    logging.getLogger().removeHandler(handler)


# ===========================================================================
# 7. Дочерние процессы: промышленный режим и миграция старой БД
# ===========================================================================
def _production_child() -> int:
    from fastapi.testclient import TestClient

    from app import auth, config
    from app import main as app_main

    out: dict[str, Any] = {}
    with TestClient(app_main.app) as client:
        creds = auth.initial_credentials_path()
        assert creds.is_file(), "не создан файл одноразовых паролей"
        lines = [ln.split("\t") for ln in creds.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
        pw = {u: p for u, _r, p in lines}
        assert set(pw) == {"admin", "engineer", "operator"}
        assert all(p not in config.KNOWN_DEFAULT_PASSWORDS and len(p) >= 16 for p in pw.values())
        bad = client.post("/api/auth/login", json={"username": "admin", "password": "GaugeAdmin!2026"}).status_code
        good = client.post("/api/auth/login", json={"username": "admin", "password": pw["admin"]}).status_code
        fault = client.post("/api/architecture/outage", json={"active": True}).status_code
        assert bad == 401 and good == 200, (bad, good)
        assert fault == 403, f"симуляция отказов вне деморежима: {fault}"
        out = {"default_login": bad, "generated_login": good, "fault_injection": fault}
    print("CHILD_RESULT " + json.dumps(out))
    return 0


def _migration_child() -> int:
    old_schema = """
    CREATE TABLE cameras (
        id TEXT PRIMARY KEY, name TEXT NOT NULL,
        type TEXT NOT NULL CHECK (type IN ('device','rtsp','http_mjpeg','phone_ws')),
        gauge_type TEXT NOT NULL DEFAULT 'pressure'
            CHECK (gauge_type IN ('pressure','temperature','draft','level','electrical','flow')),
        unit TEXT NOT NULL DEFAULT 'МПа', source_url TEXT,
        calibration TEXT NOT NULL DEFAULT '{}', thresholds TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'offline' CHECK (status IN ('online','reconnecting','offline')),
        created_at TEXT NOT NULL);
    CREATE TABLE readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
        timestamp TEXT NOT NULL, value REAL, raw_angle REAL,
        status_level TEXT NOT NULL DEFAULT 'normal' CHECK (status_level IN ('normal','warning','alert')));
    """
    dbp = Path(os.environ["GAUGEVISION_DB"])
    con = sqlite3.connect(dbp)
    con.executescript(old_schema)
    con.execute("INSERT INTO cameras (id,name,type,unit,source_url,created_at) VALUES "
                "('old-1','Старый манометр','rtsp','МПа','rtsp://192.168.0.9/live','2025-01-01T00:00:00+00:00')")
    con.executemany("INSERT INTO readings (camera_id,timestamp,value,raw_angle,status_level) VALUES (?,?,?,?,?)",
                    [("old-1", f"2026-11-2{i}T10:00:00.000+00:00", 5.0 + i, 100.0, "normal") for i in range(5)])
    con.commit()
    con.close()

    from app import db

    async def run() -> dict[str, Any]:
        await db.init_db()
        cams = await db.list_cameras()
        hist = await db.get_history("old-1", limit=50)
        await db.create_camera(name="Видео", type="video_file", source_url="bench.mp4", cam_id="new-vf")
        await db.close_db()
        return {"cams": [c["id"] for c in cams], "history": len(hist)}

    res = asyncio.run(run())
    con = sqlite3.connect(dbp)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    cols = {r[1] for r in con.execute("PRAGMA table_info(readings)")}
    con.close()
    assert "old-1" in res["cams"] and res["history"] == 5, res
    assert {"events", "users", "sessions", "auto_spec_triggers", "instrument_readings"} <= tables, tables
    assert {"unit", "run_id"} <= cols
    print("CHILD_RESULT " + json.dumps({**res, "tables": sorted(tables)}))
    return 0


def _run_child(flag: str) -> dict[str, Any]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GAUGEVISION_")}
    proc = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), flag], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env, timeout=300, cwd=str(ROOT))
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("CHILD_RESULT ")), None)
    assert proc.returncode == 0 and line, f"дочерний процесс {flag}: rc={proc.returncode}\n{proc.stdout[-1500:]}\n{proc.stderr[-2500:]}"
    return json.loads(line[len("CHILD_RESULT "):])


@case("production_mode_rejects_default_passwords", "NEW-04, REQ-SEC-05/06")
def t_production() -> dict[str, Any]:
    return _run_child("--production-child")


@case("legacy_db_migration", "REQ-ARCH-04, обратная совместимость")
def t_migration() -> dict[str, Any]:
    return _run_child("--migration-child")


def main() -> int:
    if MODE == "--production-child":
        return _production_child()
    if MODE == "--migration-child":
        return _migration_child()
    for fn in (t_dispatch_polling, t_dispatch_math, t_period_stats, t_store_forward, t_sf_overflow, t_sf_link_state, t_llm_reasoning,
               t_ring, t_spec_trips):
        fn()
    _api_checks()
    t_production()
    t_migration()
    summary = {"total": len(RESULTS), "passed": sum(r["passed"] for r in RESULTS),
               "failed": sum(not r["passed"] for r in RESULTS), "cases": RESULTS}
    out = os.environ.get("ACCEPTANCE_TEST_OUT")
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"ACCEPTANCE: {summary['passed']}/{summary['total']} PASSED")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
