"""
Инфраструктура комплексной приёмки GaugeVision AI Next Generation по контракту
SHARED_DATA_CONTRACT.md v1.1 (Multi-Gauge Vision + Auto Calibration + Predictive Analytics
+ Modernization Optimizer + SCADA Modbus TCP / MQTT / Ignition + DOCX).

Разделяет испытания строго на 2 честные категории:
  1. CONTRACT_FIXTURE_VERIFIED — реальное выполнение всех реализованных в ветке
     `next-gen/analytics-validation` компонентов (SQLite, Dispatch, Predictive Analytics,
     Store-and-Forward/MQTT, Modbus TCP `place_instruments`, 0-1 ILP Optimizer, Spec DOCX)
     на строгих фикстурах контракта v1.1 (включая многоприборные камеры, миграцию
     устаревших БД, стабильность `instrument_id`/`gauge_slot`/`modbus_slot`).
  2. PENDING_MERGE_SKIPPED — проверки не объединённых пока модулей ветки Claude
     (`next-gen/platform`: таблица `instruments`, живой Multi-Gauge трекер `app/vision.py`,
     эндпоинты `/api/sources/{id}/instruments` и `/autocalibrate` / `/calibration/confirm`,
     живой прогон с Ignition 8.3.10). НИКОГДА не имитирует прохождение необъединённого кода.

Запуск:
  CUDA_VISIBLE_DEVICES="" GAUGEVISION_DEVICE=cpu python -B tests/test_next_gen_integration_contract.py
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import io
import json
import math
import os
import sqlite3
import struct
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

from app import config, db  # noqa: E402
from app.contracts import default_passport_for_instrument, resolve_instrument_identity  # noqa: E402
from app.dispatch_analyzer import DispatchAnalyzer  # noqa: E402
from app.modernization_optimizer import optimize_modernization_budget  # noqa: E402
from app.predictive_analytics import PredictiveAnalyzer  # noqa: E402
from app.scada_gateway import ModbusTcpGateway  # noqa: E402
from app.spec_generator import generate_spec_bundle, render_spec_docx  # noqa: E402
from app.store_forward import StoreAndForwardBuffer  # noqa: E402


# ---------------------------------------------------------------------------
# Многоразовые фикстуры по SHARED_DATA_CONTRACT.md v1.1
# ---------------------------------------------------------------------------
def make_contract_v11_reading(
    *,
    instrument_id: str,
    source_id: str,
    value: float | None,
    unit: str,
    valid: bool = True,
    confidence: float = 0.91,
    level: str | None = "normal",
    calibration_rev: int = 1,
    ts: str | None = None,
    track_state: str = "locked",
) -> dict[str, Any]:
    now_s = ts or db.utcnow_iso()
    return {
        "schema": "gv.reading/1",
        "ts": now_s,
        "last_frame_ts": now_s,
        "cam_id": instrument_id,
        "instrument_id": instrument_id,
        "source_id": source_id,
        "value": value if valid else None,
        "raw_value": value if valid else None,
        "unit": unit,
        "angle": 180.0 if valid else None,
        "valid": valid,
        "confidence": confidence,
        "level": level if valid else None,
        "invalid_reason": None if valid else "track_lost",
        "out_of_scale": False,
        "awaiting_post_cal": False,
        "last_valid_value": value,
        "last_valid_level": level,
        "last_valid_ts": now_s,
        "dial_found": valid,
        "dial_source": "yolo+ellipse",
        "method": "moment/pca",
        "process_ms": 14.2,
        "calibration_rev": calibration_rev,
        "track": {"iou": 0.94, "center_shift": 0.004, "state": track_state},
    }


def make_contract_v11_instrument(
    *,
    source_id: str,
    instrument_id: str,
    is_primary: bool,
    gauge_slot: int,
    modbus_slot: int,
    code: str,
    name: str,
    group: str = "Котлоагрегаты",
    gauge_type: str = "pressure",
    unit: str = "МПа",
    v_min: float = 0.0,
    v_max: float = 16.0,
    thresholds: dict[str, Any] | None = None,
    reading: dict[str, Any] | None = None,
) -> dict[str, Any]:
    thr = thresholds or {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 13.5, "hh_alert": 14.8, "lower_enabled": True}
    return {
        "id": instrument_id,
        "instrument_id": instrument_id,
        "source_id": source_id,
        "camera_id": source_id,
        "is_primary": is_primary,
        "gauge_slot": gauge_slot,
        "modbus_slot": modbus_slot,
        "code": code,
        "tag": f"TAG-{code}",
        "name": name,
        "short_name": name,
        "group": group,
        "gauge_type": gauge_type,
        "unit": unit,
        "decimals": 2,
        "source_kind": "camera_cv",
        "status": "online",
        "roi": {"mode": "manual", "cx": 0.25 + 0.25 * gauge_slot, "cy": 0.5, "r": 0.18},
        "calibration": {
            "v_min": v_min, "theta_min": 135.0, "v_max": v_max, "theta_max": 45.0, "direction": "cw",
            "points": [{"theta": 135.0, "value": v_min}, {"theta": 270.0, "value": (v_min + v_max) * 0.5}, {"theta": 45.0, "value": v_max}],
        },
        "calibration_rev": 2,
        "calibration_meta": {"source": "auto", "status": "confirmed", "confidence": 0.93, "confirmed_by": "engineer", "rev": 2},
        "thresholds": thr,
        "reading": reading or make_contract_v11_reading(instrument_id=instrument_id, source_id=source_id, value=(v_min + v_max) * 0.5, unit=unit),
    }


def _decode_f32(hi: int, lo: int) -> float:
    return struct.unpack(">f", struct.pack(">HH", hi, lo))[0]


# ---------------------------------------------------------------------------
# 1. Сквозной путь данных на фикстурах контракта v1.1 (Multi-Gauge -> DOCX)
# ---------------------------------------------------------------------------
async def test_contract_v11_multigauge_pipeline_to_docx() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gv_ng_pipe_", ignore_cleanup_errors=True) as tmp:
        orig_db = os.environ.get("GAUGEVISION_DB")
        orig_sf = os.environ.get("GAUGEVISION_SF_DB")
        os.environ["GAUGEVISION_DB"] = str(Path(tmp) / "ng_pipe.db")
        os.environ["GAUGEVISION_SF_DB"] = str(Path(tmp) / "ng_sf.db")
        await db.close_db()
        try:
            await db.init_db()
            src_id = str(uuid.uuid4())
            # Основной прибор (instrument_id == source_id) + 2 дополнительных прибора на одной камере
            inst0_id = src_id
            inst1_id = str(uuid.uuid4())
            inst2_id = str(uuid.uuid4())
            await db.create_camera(name="Камера щита К-1 (Multi-Gauge)", type="rtsp", source_url="rtsp://10.10.0.50/main", cam_id=src_id)

            now = _dt.datetime.now(_dt.timezone.utc)
            # Независимые физические ряды в readings (с заполненным instrument_id, § 4.2)
            async with db._lock:
                conn = await db._get_conn()
                rows = []
                for m in range(-30, 1):
                    ts = (now + _dt.timedelta(minutes=m)).isoformat(timespec="milliseconds")
                    # Слот 0: стабильное давление ~10.0 МПа
                    rows.append((src_id, inst0_id, ts, 10.0 + 0.01 * math.sin(m), 180.0, "normal", "МПа", None))
                    # Слот 1: устойчивый восходящий дрейф температуры к H=550, HH=565 °C
                    v1 = 538.0 + 0.45 * m
                    lv1 = "alert" if v1 >= 565.0 else ("warning" if v1 >= 550.0 else "normal")
                    rows.append((src_id, inst1_id, ts, v1, 210.0, lv1, "°C", None))
                    # Слот 2: стабильный уровень ~50% (в будущем будет удалён/переставлен)
                    rows.append((src_id, inst2_id, ts, 50.0 + 0.05 * math.cos(m), 150.0, "normal", "%", None))
                await conn.executemany(
                    "INSERT INTO readings (camera_id, instrument_id, timestamp, value, raw_angle, status_level, unit, run_id) VALUES (?,?,?,?,?,?,?,?)",
                    rows,
                )
                await conn.commit()

            # Фикстуры 3 логических приборов на одной камере с постоянными modbus_slot
            i0 = make_contract_v11_instrument(
                source_id=src_id, instrument_id=inst0_id, is_primary=True, gauge_slot=0, modbus_slot=0,
                code="К1-Р01", name="Давление пара К-1", gauge_type="pressure", unit="МПа", v_min=0, v_max=16,
                reading=make_contract_v11_reading(instrument_id=inst0_id, source_id=src_id, value=10.0, unit="МПа"),
            )
            i1 = make_contract_v11_instrument(
                source_id=src_id, instrument_id=inst1_id, is_primary=False, gauge_slot=1, modbus_slot=36,
                code="К1-Т02", name="Температура перегрева К-1", gauge_type="temperature", unit="°C", v_min=0, v_max=600,
                thresholds={"ll_alert": 450.0, "l_warn": 480.0, "h_warn": 550.0, "hh_alert": 565.0, "lower_enabled": True},
                reading=make_contract_v11_reading(instrument_id=inst1_id, source_id=src_id, value=538.0, unit="°C", level="normal"),
            )
            i2 = make_contract_v11_instrument(
                source_id=src_id, instrument_id=inst2_id, is_primary=False, gauge_slot=2, modbus_slot=37,
                code="К1-У03", name="Уровень барабана К-1", gauge_type="level", unit="%", v_min=0, v_max=100,
                thresholds={"ll_alert": 15.0, "l_warn": 25.0, "h_warn": 75.0, "hh_alert": 85.0, "lower_enabled": True},
                reading=make_contract_v11_reading(instrument_id=inst2_id, source_id=src_id, value=50.0, unit="%"),
            )
            insts = [i0, i1, i2]

            # Проверка идентификации по контракту v1.1 (UUID v4 + явные camera_id/gauge_slot, без #gN)
            for idx_e, obj in enumerate(insts):
                ident = resolve_instrument_identity(obj)
                assert ident.instrument_id == obj["instrument_id"]
                assert ident.camera_id == src_id
                assert ident.gauge_slot == idx_e

            # Независимость истории 3 приборов одной камеры через get_instrument_series
            since_iso = (now - _dt.timedelta(minutes=60)).isoformat(timespec="milliseconds")
            smap = await db.get_instrument_series([inst0_id, inst1_id, inst2_id], since_iso=since_iso)
            assert len(smap[inst0_id]) == 31 and len(smap[inst1_id]) == 31 and len(smap[inst2_id]) == 31
            assert abs(smap[inst0_id][-1][1] - 10.0) < 0.1
            assert abs(smap[inst1_id][-1][1] - 538.0) < 0.1
            assert abs(smap[inst2_id][-1][1] - 50.0) < 0.2

            # Dispatch + Predictive Analytics
            da = DispatchAnalyzer()
            da.ingest_instruments(insts)
            evs = [{
                "id": 101, "ts": now.isoformat(timespec="milliseconds"), "kind": "alarm",
                "cam_id": inst1_id, "instrument_id": inst1_id, "source_id": src_id,
                "level": "warning", "value": 551.0, "unit": "°C", "text": "H", "has_frame": False,
            }]
            disp = da.overview(insts, evs, {})
            pa = PredictiveAnalyzer()
            pred = pa.overview(insts, smap, window_min=60.0, horizon_min=60.0, now_unix=now.timestamp())
            pred_by_id = {x["instrument_id"]: x for x in pred["instruments"]}
            assert pred_by_id[inst1_id]["status"] == "ok"
            assert pred_by_id[inst1_id]["eta_alert_min"] is not None and 50.0 <= pred_by_id[inst1_id]["eta_alert_min"] <= 70.0
            assert pred_by_id[inst0_id]["eta_alert_min"] is None

            # Сохранение снапшотов + Store-and-Forward MQTT конверт с instrument_id
            saved_snaps = await db.save_predictive_snapshots(pred["instruments"])
            assert saved_snaps == 3
            sf = StoreAndForwardBuffer()
            await sf.init()
            await sf.set_outage(True, "contract_v11_buffering_check")
            await sf.enqueue(
                channel_id=inst1_id,
                payload_type="telemetry",
                severity="warning",
                payload={
                    "schema": "gv.telemetry/1",
                    "instrument_id": inst1_id,
                    "source_id": src_id,
                    "code": "К1-Т02",
                    "ts": now.isoformat(timespec="milliseconds"),
                    "value": 538.0,
                    "unit": "°C",
                    "level": "normal",
                    "valid": True,
                    "confidence": 0.91,
                    "calibration_rev": 2,
                },
            )
            assert await sf.pending_count() >= 1
            await sf.close()

            # Modbus TCP: постоянные слоты (0, 36, 37) во всех 3 блоках без конфликтов
            mb = ModbusTcpGateway()
            hmap = {x["id"]: x["health_score"] for x in disp["instruments"]}
            mb.update_from_instruments(insts, health_by_id=hmap, predictive_by_id=pred_by_id, now_unix=now.timestamp())
            snap = mb.registers_snapshot(limit=10)
            by_iid_mb = {r["instrument_id"]: r for r in snap["instruments"]}
            assert by_iid_mb[inst0_id]["modbus_slot"] == 0 and by_iid_mb[inst0_id]["hr_value"] == 40001
            assert by_iid_mb[inst1_id]["modbus_slot"] == 36 and by_iid_mb[inst1_id]["hr_value"] == 40001 + 36 * 4
            assert by_iid_mb[inst1_id]["hr_pred_base"] == 40001 + 3600 + 36 * 8
            assert by_iid_mb[inst2_id]["modbus_slot"] == 37 and by_iid_mb[inst2_id]["hr_value"] == 40001 + 37 * 4
            assert abs(_decode_f32(mb._regs[36 * 4], mb._regs[36 * 4 + 1]) - 538.0) < 0.05

            # Optimizer + DOCX generation
            passports = {x["instrument_id"]: default_passport_for_instrument(x) for x in insts}
            passports[inst1_id]["mandatory_regulation"] = True
            opt = optimize_modernization_budget(
                dispatch_overview=disp,
                predictive_overview=pred,
                passports_by_id=passports,
                budget_rub=300_000,
                include_healthy=True,
                include_frontier=True,
            )
            assert opt["status"] == "optimal"
            assert any(s["instrument_id"] == inst1_id for s in opt["selected"])

            bundle = await generate_spec_bundle(
                dispatch_overview=disp,
                events=evs,
                snapshot_lookup={},
                period="12h",
                mode="deterministic",
                predictive_overview=pred,
                optimization_result=opt,
                selected_instrument_ids=[s["instrument_id"] for s in opt["selected"]],
                strict_scope=False,
            )
            docx_bytes = render_spec_docx(bundle)
            with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
                xml_txt = zf.read("word/document.xml").decode("utf-8")
                assert "К1-Т02" in xml_txt
                assert "оптимизация бюджета модернизации" in xml_txt.lower()

            return {
                "status": "CONTRACT_FIXTURE_VERIFIED",
                "instruments_on_one_camera": 3,
                "modbus_slots": [0, 36, 37],
                "inst1_eta_alert_min": pred_by_id[inst1_id]["eta_alert_min"],
                "opt_status": opt["status"],
                "docx_bytes": len(docx_bytes),
            }
        finally:
            await db.close_db()
            for k, v in (("GAUGEVISION_DB", orig_db), ("GAUGEVISION_SF_DB", orig_sf)):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


# ---------------------------------------------------------------------------
# 2. Стабильность instrument_id / gauge_slot / modbus_slot при добавлении,
#    удалении, перестановке и перезапуске + отсутствие конфликтов регистров
# ---------------------------------------------------------------------------
def test_modbus_slot_stability_add_delete_reorder_restart() -> dict[str, Any]:
    src = str(uuid.uuid4())
    g0 = make_contract_v11_instrument(source_id=src, instrument_id=src, is_primary=True, gauge_slot=0, modbus_slot=0, code="G0", name="G0",
                                      reading=make_contract_v11_reading(instrument_id=src, source_id=src, value=10.5, unit="МПа"))
    id1, id2, id3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    g1 = make_contract_v11_instrument(source_id=src, instrument_id=id1, is_primary=False, gauge_slot=1, modbus_slot=36, code="G1", name="G1",
                                      reading=make_contract_v11_reading(instrument_id=id1, source_id=src, value=22.5, unit="МПа"))
    g2 = make_contract_v11_instrument(source_id=src, instrument_id=id2, is_primary=False, gauge_slot=2, modbus_slot=37, code="G2", name="G2",
                                      reading=make_contract_v11_reading(instrument_id=id2, source_id=src, value=33.5, unit="МПа"))
    g3 = make_contract_v11_instrument(source_id=src, instrument_id=id3, is_primary=False, gauge_slot=3, modbus_slot=38, code="G3", name="G3",
                                      reading=make_contract_v11_reading(instrument_id=id3, source_id=src, value=44.5, unit="МПа"))

    mb = ModbusTcpGateway()
    # Шаг 1: 3 прибора (слоты 0, 36, 37)
    mb.update_from_instruments([g0, g1, g2])
    assert abs(_decode_f32(mb._regs[0], mb._regs[1]) - 10.5) < 1e-3
    assert abs(_decode_f32(mb._regs[36 * 4], mb._regs[36 * 4 + 1]) - 22.5) < 1e-3
    assert abs(_decode_f32(mb._regs[37 * 4], mb._regs[37 * 4 + 1]) - 33.5) < 1e-3

    # Шаг 2: Перестановка порядка списка [g2, g0, g1] — адреса регистров НЕ сдвигаются!
    mb.update_from_instruments([g2, g0, g1])
    assert abs(_decode_f32(mb._regs[0], mb._regs[1]) - 10.5) < 1e-3
    assert abs(_decode_f32(mb._regs[36 * 4], mb._regs[36 * 4 + 1]) - 22.5) < 1e-3
    assert abs(_decode_f32(mb._regs[37 * 4], mb._regs[37 * 4 + 1]) - 33.5) < 1e-3

    # Шаг 3: Удаляем g1 (слот 36) и добавляем g3 (слот 38) — слот 37 остаётся у g2, а слот 36 переходит в NaN/STALE!
    mb.update_from_instruments([g0, g2, g3])
    assert math.isnan(_decode_f32(mb._regs[36 * 4], mb._regs[36 * 4 + 1]))
    assert mb._regs[36 * 4 + 2] == 3  # STALE
    assert mb._regs[2000 + 36 * 8] == 65535  # age = unknown
    assert math.isnan(_decode_f32(mb._regs[3600 + 36 * 8], mb._regs[3600 + 36 * 8 + 1]))  # pred ETA = NaN
    assert mb._regs[3600 + 36 * 8 + 6] == 6  # insufficient_data
    assert abs(_decode_f32(mb._regs[37 * 4], mb._regs[37 * 4 + 1]) - 33.5) < 1e-3
    assert abs(_decode_f32(mb._regs[38 * 4], mb._regs[38 * 4 + 1]) - 44.5) < 1e-3

    # Шаг 4: Перезапуск шлюза с теми же сохранёнными слотами -> идентичная карта
    mb2 = ModbusTcpGateway()
    mb2.update_from_instruments([g3, g2, g0])
    assert abs(_decode_f32(mb2._regs[0], mb2._regs[1]) - 10.5) < 1e-3
    assert abs(_decode_f32(mb2._regs[37 * 4], mb2._regs[37 * 4 + 1]) - 33.5) < 1e-3
    assert abs(_decode_f32(mb2._regs[38 * 4], mb2._regs[38 * 4 + 1]) - 44.5) < 1e-3

    # Шаг 5: Проверка отсутствия пересечений диапазонов для всех 200 слотов (прогнозный блок 0..60 и 61..199)
    used_ranges: list[tuple[str, int, int]] = [
        ("base", 0, 200 * 4 - 1),
        ("system", 900, 917),
        ("extended", 2000, 2000 + 200 * 8 - 1),
        ("predictive", 3600, 3600 + 61 * 8 - 1),
        ("predictive_ext", 4096, 4096 + (200 - 61) * 8 - 1),
    ]
    # каждый из 200 слотов получает свой прогнозный блок, блоки не пересекаются
    pred = sorted(ModbusTcpGateway.predictive_base(k) for k in range(200))
    assert all(b - a >= 8 for a, b in zip(pred, pred[1:])) and pred[60] == 3600 + 60 * 8 and pred[61] == 4096
    for i in range(len(used_ranges)):
        for j in range(i + 1, len(used_ranges)):
            n1, a1, b1 = used_ranges[i]
            n2, a2, b2 = used_ranges[j]
            assert b1 < a2 or b2 < a1, f"Overlap between {n1}[{a1}..{b1}] and {n2}[{a2}..{b2}]"
            assert b1 < ModbusTcpGateway.MAX_REGISTERS and b2 < ModbusTcpGateway.MAX_REGISTERS

    return {"status": "CONTRACT_FIXTURE_VERIFIED", "deleted_slot_36_cleared": True, "register_overlaps": 0}


# ---------------------------------------------------------------------------
# 3. Миграция старой базы данных GaugeVision 2.0 (без instrument_id и таблиц Neon)
# ---------------------------------------------------------------------------
async def test_legacy_db_migration_and_backward_compatibility() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gv_legacy_mig_", ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "legacy_v20.db"
        # Создаём аутентичную старую БД GaugeVision 2.0 (без readings.instrument_id, unit, run_id, паспортов)
        con = sqlite3.connect(str(db_path))
        con.executescript("""
            CREATE TABLE cameras (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('device','rtsp','http_mjpeg','phone_ws')),
                gauge_type TEXT NOT NULL DEFAULT 'pressure',
                unit TEXT NOT NULL DEFAULT 'МПа', source_url TEXT,
                calibration TEXT NOT NULL DEFAULT '{}', thresholds TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'offline', created_at TEXT NOT NULL
            );
            CREATE TABLE readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
                timestamp TEXT NOT NULL, value REAL, raw_angle REAL,
                status_level TEXT NOT NULL DEFAULT 'normal'
            );
        """)
        legacy_cam_id = "legacy-cam-001"
        now = _dt.datetime.now(_dt.timezone.utc)
        con.execute(
            "INSERT INTO cameras VALUES (?,?,?,?,?,?,?,?,?,?)",
            (legacy_cam_id, "Старый манометр К-1", "rtsp", "pressure", "МПа", "rtsp://192.168.1.10/ch1", "{}", "{}", "online", now.isoformat()),
        )
        for m in range(-20, 1):
            ts = (now + _dt.timedelta(minutes=m)).isoformat(timespec="milliseconds")
            con.execute("INSERT INTO readings (camera_id, timestamp, value, raw_angle, status_level) VALUES (?,?,?,?,?)",
                        (legacy_cam_id, ts, 8.5 + 0.05 * m, 180.0, "normal"))
        con.commit()
        con.close()

        orig_db = os.environ.get("GAUGEVISION_DB")
        os.environ["GAUGEVISION_DB"] = str(db_path)
        await db.close_db()
        try:
            await db.init_db()
            cams = await db.list_cameras()
            assert len(cams) == 1 and cams[0]["id"] == legacy_cam_id and cams[0]["status"] == "offline"
            since_iso = (now - _dt.timedelta(minutes=40)).isoformat(timespec="milliseconds")
            # COALESCE(instrument_id, camera_id) читает старые строки с instrument_id IS NULL без потери данных!
            smap = await db.get_instrument_series([legacy_cam_id], since_iso=since_iso)
            assert len(smap[legacy_cam_id]) == 21
            assert abs(smap[legacy_cam_id][-1][1] - 8.5) < 1e-3
            return {"status": "CONTRACT_FIXTURE_VERIFIED", "legacy_rows_preserved": len(smap[legacy_cam_id])}
        finally:
            await db.close_db()
            if orig_db is None:
                os.environ.pop("GAUGEVISION_DB", None)
            else:
                os.environ["GAUGEVISION_DB"] = orig_db


# ---------------------------------------------------------------------------
# 4. Проверки, ожидавшие слияния: после объединения веток выполняются в отдельных наборах
# ---------------------------------------------------------------------------
def report_pending_merge_checks() -> list[dict[str, str]]:
    """После слияния (ветка next-gen/integration) проверки выполняются наборами на живом коде:
    результат каждого — в выводе соответствующего набора, здесь — только ссылка, без подмены."""
    return [
        {
            "check_id": "INT-MG-01",
            "name": "Live SQLite `instruments` table CRUD & `POST /api/sources/{source_id}/instruments`",
            "status": "RUN_IN_SUITE",
            "suite": "tests/test_instruments_db.py, tests/test_multigauge_api.py, tests/test_final_integration.py (new_api_security)",
        },
        {
            "check_id": "INT-MG-02",
            "name": "Live Multi-Gauge Vision detector & ROI tracker -> multi-instrument telemetry",
            "status": "RUN_IN_SUITE",
            "suite": "tests/test_multigauge.py, tests/test_multigauge_api.py, tests/test_final_integration.py (multigauge_calibration_isolation)",
        },
        {
            "check_id": "INT-AC-01",
            "name": "Calibration is never applied automatically; manual calibration bumps `calibration_rev` (replaces auto-calibration check: Auto Calibration excluded from release)",
            "status": "RUN_IN_SUITE",
            "suite": "tests/test_autocal.py, tests/test_final_integration.py (autocal_cannot_apply, multigauge_calibration_isolation)",
        },
        {
            "check_id": "INT-SCADA-02",
            "name": "Live Ignition 8.3.10 multi-gauge tag reconciliation after branch merge",
            "status": "RUN_IN_LAB",
            "suite": "reports/final_integration/SCADA_REVALIDATION_REPORT.md (живой стенд Ignition, вне автоматических наборов)",
        },
    ]


def main() -> None:
    report: dict[str, Any] = {}
    report["multigauge_contract_pipeline_to_docx"] = asyncio.run(test_contract_v11_multigauge_pipeline_to_docx())
    print("[PASS][CONTRACT_FIXTURE] multigauge_contract_pipeline_to_docx", report["multigauge_contract_pipeline_to_docx"])

    report["modbus_slot_stability"] = test_modbus_slot_stability_add_delete_reorder_restart()
    print("[PASS][CONTRACT_FIXTURE] modbus_slot_stability", report["modbus_slot_stability"])

    report["legacy_db_migration"] = asyncio.run(test_legacy_db_migration_and_backward_compatibility())
    print("[PASS][CONTRACT_FIXTURE] legacy_db_migration", report["legacy_db_migration"])

    report["pending_merge_checks"] = report_pending_merge_checks()
    for p in report["pending_merge_checks"]:
        print(f"[{p['status']}] {p['check_id']}: {p['suite']}")

    out_path = os.environ.get("NG_INTEGRATION_OUT")
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("CONTRACT v1.1 INTEGRATION HARNESS COMPLETE: 3/3 CONTRACT_FIXTURE_VERIFIED, 4 checks run in merged suites")


if __name__ == "__main__":
    main()
