"""
Хранилище логических приборов (SHARED_DATA_CONTRACT § 4): миграция старой базы, основной прибор
камеры, дополнительные приборы, раздельная история, ревизии калибровки, постоянные слоты Modbus.

Запуск:
  python -B tests/test_instruments_db.py
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="gv_inst_db_"))
os.environ["GAUGEVISION_DB"] = str(_TMP / "main.db")

from app import config, db  # noqa: E402

# Схема до Multi-Gauge (камера = прибор), как в базах развёрнутых версий
LEGACY_DDL = """
CREATE TABLE cameras (
    id TEXT PRIMARY KEY, name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('device','rtsp','http_mjpeg','phone_ws','video_file')),
    gauge_type TEXT NOT NULL DEFAULT 'pressure', unit TEXT NOT NULL DEFAULT 'МПа', source_url TEXT,
    calibration TEXT NOT NULL DEFAULT '{}', thresholds TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'offline', created_at TEXT NOT NULL
);
CREATE TABLE readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, camera_id TEXT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    timestamp TEXT NOT NULL, value REAL, raw_angle REAL, status_level TEXT NOT NULL DEFAULT 'normal',
    unit TEXT, run_id TEXT
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, cam_id TEXT, cam_name TEXT, level TEXT,
    prev_level TEXT, value REAL, unit TEXT, setpoint TEXT, setpoint_value REAL, text TEXT NOT NULL DEFAULT '',
    has_frame INTEGER NOT NULL DEFAULT 0, acked INTEGER NOT NULL DEFAULT 0, acked_ts TEXT, acked_by TEXT,
    ref_event_id INTEGER, ref_ts TEXT, ref_level TEXT, duration_s REAL, snapshot_blob BLOB
);
"""


def _use_db(path: Path) -> None:
    os.environ["GAUGEVISION_DB"] = str(path)


async def legacy_migration() -> dict:
    path = _TMP / "legacy.db"
    con = sqlite3.connect(path)
    con.executescript(LEGACY_DDL)
    cal = '{"v_min": 0, "theta_min": 135, "v_max": 16, "theta_max": 45, "direction": "cw"}'
    con.execute("INSERT INTO cameras VALUES ('cam-b','Б','rtsp','pressure','МПа',NULL,?, '{}','online','2026-01-02T00:00:00+00:00')", (cal,))
    con.execute("INSERT INTO cameras VALUES ('cam-a','А','device','pressure','МПа',NULL,?, '{\"h_warn\": 12}','offline','2026-01-01T00:00:00+00:00')", (cal,))
    for k in range(5):
        con.execute("INSERT INTO readings (camera_id, timestamp, value, raw_angle, status_level) VALUES (?,?,?,?,?)",
                    ("cam-a", f"2026-01-01T00:00:0{k}.000+00:00", 1.0 + k, 100.0, "normal"))
    con.execute("INSERT INTO events (id, ts, kind, cam_id, text) VALUES (7, '2026-01-01T00:00:00+00:00', 'alarm', 'cam-a', '')")
    con.commit()
    con.close()

    await db.close_db()
    _use_db(path)
    await db.init_db()
    await db.init_db()  # повторный запуск миграции ничего не ломает
    insts = await db.list_instruments()
    assert [i["id"] for i in insts] == ["cam-a", "cam-b"], insts
    assert all(i["is_primary"] and i["source_id"] == i["id"] for i in insts)
    assert [i["modbus_slot"] for i in insts] == [0, 1], "слоты по порядку создания камер (как прежняя позиция)"
    assert insts[0]["thresholds"]["h_warn"] == 12 and insts[0]["calibration"]["v_max"] == 16
    hist = await db.get_history("cam-a", 10)
    assert len(hist) == 5 and all(r["instrument_id"] == "cam-a" for r in hist)
    events, _ = await db.load_persisted_events()
    assert events and events[0]["cam_id"] == "cam-a" and events[0]["instrument_id"] is None
    await db.close_db()
    return {"instruments": len(insts), "history_rows": len(hist)}


async def multi_instrument_flow() -> dict:
    _use_db(_TMP / "flow.db")
    await db.init_db()
    cam = await db.create_camera(name="Щит 1", type="rtsp", source_url="rtsp://10.0.0.5/s1")
    prim = await db.get_instrument(cam["id"])
    assert prim and prim["is_primary"] and prim["modbus_slot"] == 0

    extra = []
    for k in range(3):
        extra.append(await db.create_instrument(
            source_id=cam["id"], name=f"PI-10{k + 2}", code=f"PI-10{k + 2}",
            roi={"mode": "auto", "cx": 0.2 + 0.3 * k, "cy": 0.5, "r": 0.12},
            calibration={"v_min": 0, "v_max": 1.6, "theta_min": 135, "theta_max": 45},
        ))
    slots = [prim["modbus_slot"]] + [e["modbus_slot"] for e in extra]
    assert slots == [0, 1, 2, 3], slots
    assert len(await db.list_instruments(cam["id"])) == 4

    # раздельная история приборов одного источника
    await db.insert_readings([
        (cam["id"], "2026-02-01T00:00:00.000+00:00", 5.0, 10.0, "normal", "МПа", None),
        (cam["id"], "2026-02-01T00:00:01.000+00:00", 0.8, 20.0, "normal", "МПа", None, extra[0]["id"], 0),
        (cam["id"], "2026-02-01T00:00:02.000+00:00", 0.9, 21.0, "warning", "МПа", None, extra[0]["id"], 0),
    ])
    assert [r["value"] for r in await db.get_history(cam["id"], 10)] == [5.0]
    assert [r["value"] for r in await db.get_history(extra[0]["id"], 10)] == [0.8, 0.9]
    assert [i["gauge_slot"] for i in [prim, *extra]] == [0, 1, 2, 3]
    assert all(r["calibration_rev"] == 0 for r in await db.get_history(extra[0]["id"], 10))

    # ревизия калибровки растёт только при смене шкалы
    upd = await db.update_instrument(extra[0]["id"], {"thresholds": {"h_warn": 1.2}})
    assert upd["calibration_rev"] == 0
    upd = await db.update_instrument(extra[0]["id"], {"calibration": {**upd["calibration"], "v_max": 2.5}})
    assert upd["calibration_rev"] == 1 and upd["calibration_meta"]["rev"] == 1
    assert upd["calibration_meta"]["status"] == "confirmed"

    # старый API камеры меняет основной прибор, и наоборот
    await db.update_camera(cam["id"], {"calibration": {"v_min": 0, "v_max": 25, "theta_min": 135, "theta_max": 45,
                                                       "direction": "cw"}, "name": "Щит 1 (переим.)"})
    prim = await db.get_instrument(cam["id"])
    assert prim["calibration"]["v_max"] == 25 and prim["calibration_rev"] == 1 and prim["name"] == "Щит 1 (переим.)"
    await db.update_instrument(cam["id"], {"thresholds": {"h_warn": 20.0}})
    assert (await db.get_camera(cam["id"]))["thresholds"]["h_warn"] == 20.0

    # основной прибор отдельно не удаляется; дополнительный — вместе с историей
    assert await db.delete_instrument(cam["id"]) is False
    assert await db.delete_instrument(extra[0]["id"]) is True
    assert await db.get_history(extra[0]["id"], 10) == []
    # освободившийся слот не переназначает существующие
    new = await db.create_instrument(source_id=cam["id"], name="PI-200", roi={"mode": "auto", "cx": 0.5, "cy": 0.2, "r": 0.1})
    assert new["modbus_slot"] == 1 and (await db.get_instrument(extra[1]["id"]))["modbus_slot"] == 2
    assert new["gauge_slot"] == 1, "номер циферблата удалённого прибора свободен"

    # удаление камеры удаляет её приборы
    await db.delete_camera(cam["id"])
    assert await db.list_instruments(cam["id"]) == []
    await db.close_db()
    return {"slots": slots}


async def demo_slots() -> dict:
    _use_db(_TMP / "demo.db")
    prev = os.environ.get("GAUGEVISION_DEMO")
    os.environ["GAUGEVISION_DEMO"] = "1"
    try:
        assert config.is_demo_mode()
        await db.init_db()
        live = await db.create_camera(name="Живой", type="phone_ws", cam_id=config.DEMO_LIVE_CAM_ID)
        other = await db.create_camera(name="Доп.", type="rtsp")
        extra = await db.create_instrument(source_id=live["id"], name="Второй", roi={"cx": 0.3, "cy": 0.3, "r": 0.1})
        got = [(await db.get_instrument(i))["modbus_slot"] for i in (live["id"], other["id"], extra["id"])]
        # 1–35 заняты симуляцией стенда: дополнительные приборы — с 36
        assert got == [0, config.DEMO_TOTAL_POSITIONS, config.DEMO_TOTAL_POSITIONS + 1], got
        await db.close_db()
        return {"slots": got}
    finally:
        if prev is None:
            os.environ.pop("GAUGEVISION_DEMO", None)
        else:
            os.environ["GAUGEVISION_DEMO"] = prev


async def main() -> None:
    print("[legacy_migration]", await legacy_migration())
    print("[multi_instrument_flow]", await multi_instrument_flow())
    print("[demo_slots]", await demo_slots())
    print("ALL INSTRUMENT DB TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
