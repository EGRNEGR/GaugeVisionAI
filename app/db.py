"""
GaugeVision AI — слой данных SQLite (aiosqlite).

Таблицы `cameras` и `readings` строго по разделу 8 ТЗ.
Репозиторий телеметрии: батч-запись отсчётов, история, CSV-экспорт.

Используется одно долгоживущее соединение (WAL-режим) с asyncio.Lock —
это быстрее, чем открывать файл БД на каждый запрос, и безопасно для
конкурентных корутин одного event-loop.
"""
from __future__ import annotations

import asyncio
import csv
import datetime as _dt
import io
import json
import uuid
from typing import Any, Iterable

import aiosqlite

from . import config

_lock = asyncio.Lock()
_conn: aiosqlite.Connection | None = None


# ---------------------------------------------------------------------------
# Вспомогательные
# ---------------------------------------------------------------------------
def utcnow_iso() -> str:
    """Текущее время UTC в ISO 8601 с миллисекундами."""
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


def new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Схема БД
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    type         TEXT NOT NULL CHECK (type IN ('device','rtsp','http_mjpeg','phone_ws')),
    gauge_type   TEXT NOT NULL DEFAULT 'pressure'
                 CHECK (gauge_type IN ('pressure','temperature','draft','level','electrical','flow')),
    unit         TEXT NOT NULL DEFAULT 'МПа',
    source_url   TEXT,
    calibration  TEXT NOT NULL DEFAULT '{}',
    thresholds   TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'offline' CHECK (status IN ('online','reconnecting','offline')),
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS readings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id    TEXT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    timestamp    TEXT NOT NULL,
    value        REAL,
    raw_angle    REAL,
    status_level TEXT NOT NULL DEFAULT 'normal' CHECK (status_level IN ('normal','warning','alert'))
);

CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings (timestamp);
CREATE INDEX IF NOT EXISTS idx_readings_cam_ts ON readings (camera_id, timestamp);
"""

DEFAULT_THRESHOLDS: dict[str, float | None] = {
    "ll_alert": None,
    "l_warn": None,
    "h_warn": None,
    "hh_alert": None,
}

# Углы в системе координат изображения (ось Y вниз): 0° — «3 часа», 90° — «6 часов».
# Типовая шкала 270°: минимум на «7:30» (135°), максимум на «4:30» (45°), по часовой.
DEFAULT_CALIBRATION: dict[str, Any] = {
    "v_min": 0.0,
    "theta_min": 135.0,
    "v_max": 10.0,
    "theta_max": 45.0,
    "direction": "cw",
}


async def _get_conn() -> aiosqlite.Connection:
    global _conn
    if _conn is None:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = await aiosqlite.connect(str(config.DB_PATH), timeout=30)
        _conn.row_factory = aiosqlite.Row
        await _conn.execute("PRAGMA journal_mode=WAL")
        await _conn.execute("PRAGMA synchronous=NORMAL")
        await _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


async def init_db() -> None:
    """Создаёт/открывает БД, применяет схему, сбрасывает статусы камер."""
    async with _lock:
        conn = await _get_conn()
        await conn.executescript(SCHEMA)
        # после перезапуска сервера ни один поток ещё не подключён
        await conn.execute("UPDATE cameras SET status = 'offline'")
        await conn.commit()


async def close_db() -> None:
    global _conn
    async with _lock:
        if _conn is not None:
            try:
                await _conn.close()
            finally:
                _conn = None


def _row_to_camera(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        calib = json.loads(d.get("calibration") or "{}")
    except json.JSONDecodeError:
        calib = {}
    try:
        thr = json.loads(d.get("thresholds") or "{}")
    except json.JSONDecodeError:
        thr = {}
    d["calibration"] = {**DEFAULT_CALIBRATION, **calib}
    d["thresholds"] = {**DEFAULT_THRESHOLDS, **thr}
    return d


# ---------------------------------------------------------------------------
# Репозиторий: cameras
# ---------------------------------------------------------------------------
async def list_cameras() -> list[dict[str, Any]]:
    async with _lock:
        conn = await _get_conn()
        cur = await conn.execute("SELECT * FROM cameras ORDER BY created_at ASC")
        rows = await cur.fetchall()
    return [_row_to_camera(r) for r in rows]


async def get_camera(cam_id: str) -> dict[str, Any] | None:
    async with _lock:
        conn = await _get_conn()
        cur = await conn.execute("SELECT * FROM cameras WHERE id = ?", (cam_id,))
        row = await cur.fetchone()
    return _row_to_camera(row) if row else None


async def create_camera(
    *,
    name: str,
    type: str,
    gauge_type: str = "pressure",
    unit: str | None = None,
    source_url: str | None = None,
    calibration: dict | None = None,
    thresholds: dict | None = None,
    cam_id: str | None = None,
) -> dict[str, Any]:
    cam_id = cam_id or new_uuid()
    unit = unit or config.GAUGE_TYPES[gauge_type]["units"][0]
    calib = {**DEFAULT_CALIBRATION, **(calibration or {})}
    thr = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    async with _lock:
        conn = await _get_conn()
        await conn.execute(
            """INSERT INTO cameras
               (id, name, type, gauge_type, unit, source_url,
                calibration, thresholds, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                cam_id, name, type, gauge_type, unit, source_url,
                json.dumps(calib, ensure_ascii=False),
                json.dumps(thr, ensure_ascii=False),
                "offline", utcnow_iso(),
            ),
        )
        await conn.commit()
    return await get_camera(cam_id)  # type: ignore[return-value]


async def update_camera(cam_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    """Частичное обновление камеры (имя, тип, единицы, калибровка, уставки)."""
    allowed = {
        "name", "type", "gauge_type", "unit", "source_url",
        "calibration", "thresholds", "status",
    }
    sets: list[str] = []
    vals: list[Any] = []
    for k, v in patch.items():
        if k not in allowed:
            continue
        if k in ("calibration", "thresholds"):
            v = json.dumps(v or {}, ensure_ascii=False)
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return await get_camera(cam_id)
    vals.append(cam_id)
    async with _lock:
        conn = await _get_conn()
        await conn.execute(f"UPDATE cameras SET {', '.join(sets)} WHERE id = ?", vals)
        await conn.commit()
    return await get_camera(cam_id)


async def set_camera_status(cam_id: str, status: str) -> None:
    async with _lock:
        conn = await _get_conn()
        await conn.execute("UPDATE cameras SET status = ? WHERE id = ?", (status, cam_id))
        await conn.commit()


async def delete_camera(cam_id: str) -> bool:
    async with _lock:
        conn = await _get_conn()
        await conn.execute("DELETE FROM readings WHERE camera_id = ?", (cam_id,))
        cur = await conn.execute("DELETE FROM cameras WHERE id = ?", (cam_id,))
        await conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Репозиторий: readings
# ---------------------------------------------------------------------------
async def insert_reading(
    camera_id: str, value: float | None, raw_angle: float | None, status_level: str,
    timestamp: str | None = None,
) -> None:
    await insert_readings([(camera_id, timestamp or utcnow_iso(), value, raw_angle, status_level)])


async def insert_readings(rows: Iterable[tuple[str, str, float | None, float | None, str]]) -> None:
    """Батч-запись отсчётов: (camera_id, timestamp, value, raw_angle, status_level)."""
    rows = list(rows)
    if not rows:
        return
    async with _lock:
        conn = await _get_conn()
        await conn.executemany(
            """INSERT INTO readings (camera_id, timestamp, value, raw_angle, status_level)
               VALUES (?,?,?,?,?)""",
            rows,
        )
        await conn.commit()


async def get_history(camera_id: str, limit: int = config.HISTORY_DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Последние `limit` отсчётов камеры в хронологическом порядке."""
    async with _lock:
        conn = await _get_conn()
        cur = await conn.execute(
            """SELECT id, camera_id, timestamp, value, raw_angle, status_level
               FROM readings WHERE camera_id = ?
               ORDER BY id DESC LIMIT ?""",
            (camera_id, int(limit)),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in reversed(rows)]


async def export_csv(camera_id: str, limit: int = 1_000_000) -> str:
    """Экспорт истории телеметрии в CSV (временные метки ISO 8601, UTC)."""
    cam = await get_camera(camera_id)
    unit = cam["unit"] if cam else ""
    history = await get_history(camera_id, limit)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["timestamp_iso8601", f"value_{unit}", "raw_angle_deg", "status_level"])
    for r in history:
        writer.writerow([
            r["timestamp"],
            "" if r["value"] is None else f"{r['value']:.4f}",
            "" if r["raw_angle"] is None else f"{r['raw_angle']:.2f}",
            r["status_level"],
        ])
    return buf.getvalue()


async def clear_history(camera_id: str) -> None:
    async with _lock:
        conn = await _get_conn()
        await conn.execute("DELETE FROM readings WHERE camera_id = ?", (camera_id,))
        await conn.commit()


async def prune_history(keep_days: int = 90) -> int:
    """Удаляет отсчёты старше `keep_days` суток; возвращает число удалённых строк."""
    cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=keep_days)).isoformat()
    async with _lock:
        conn = await _get_conn()
        cur = await conn.execute("DELETE FROM readings WHERE timestamp < ?", (cutoff,))
        await conn.commit()
        return cur.rowcount or 0
