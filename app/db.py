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

CREATE TABLE IF NOT EXISTS demo_runs (
    id           TEXT PRIMARY KEY,
    camera_id    TEXT NOT NULL,
    label        TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    unit         TEXT NOT NULL DEFAULT 'МПа',
    calibration  TEXT NOT NULL DEFAULT '{}',
    thresholds   TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_demo_runs_created ON demo_runs (created_at);
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
    db_file = config.get_db_path()
    if _conn is None:
        db_file.parent.mkdir(parents=True, exist_ok=True)
        _conn = await aiosqlite.connect(str(db_file), timeout=30)
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
        cur = await conn.execute("PRAGMA table_info(readings)")
        cols = {row["name"] for row in await cur.fetchall()}
        if "unit" not in cols:
            await conn.execute("ALTER TABLE readings ADD COLUMN unit TEXT")
        if "run_id" not in cols:
            await conn.execute("ALTER TABLE readings ADD COLUMN run_id TEXT")
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
    timestamp: str | None = None, unit: str | None = None, run_id: str | None = None,
) -> None:
    await insert_readings([(camera_id, timestamp or utcnow_iso(), value, raw_angle, status_level, unit, run_id)])


async def insert_readings(rows: Iterable[tuple[Any, ...]]) -> None:
    """Батч-запись отсчётов: (camera_id, timestamp, value, raw_angle, status_level[, unit, run_id])."""
    norm_rows = []
    for r in rows:
        if len(r) == 5:
            norm_rows.append((*r, None, None))
        elif len(r) == 6:
            norm_rows.append((*r, None))
        else:
            norm_rows.append(tuple(r[:7]))
    if not norm_rows:
        return
    async with _lock:
        conn = await _get_conn()
        await conn.executemany(
            """INSERT INTO readings (camera_id, timestamp, value, raw_angle, status_level, unit, run_id)
               VALUES (?,?,?,?,?,?,?)""",
            norm_rows,
        )
        await conn.commit()


async def get_history(camera_id: str, limit: int = config.HISTORY_DEFAULT_LIMIT,
                      *, since: str | None = None, until: str | None = None,
                      run_id: str | None = None) -> list[dict[str, Any]]:
    """Последние `limit` достоверных отсчётов камеры в хронологическом порядке."""
    clauses = ["camera_id = ?"]
    params: list[Any] = [camera_id]
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if since:
        clauses.append("timestamp >= ?")
        params.append(since)
    if until:
        clauses.append("timestamp <= ?")
        params.append(until)
    if run_id or since or until:
        clauses.append("value IS NOT NULL")
    where_sql = " AND ".join(clauses)
    params.append(int(limit))
    async with _lock:
        conn = await _get_conn()
        cur = await conn.execute(
            f"""SELECT id, camera_id, timestamp, value, raw_angle, status_level, unit, run_id
                FROM readings WHERE {where_sql}
                ORDER BY timestamp DESC, id DESC LIMIT ?""",
            params,
        )
        rows = await cur.fetchall()
    return [dict(r) for r in reversed(rows)]


async def get_trend(camera_id: str, since: _dt.datetime, step_s: float,
                    until: _dt.datetime | None = None) -> list[dict[str, Any]]:
    """
    Агрегированный тренд с момента `since` (и до `until`, если задано): корзины по `step_s` секунд
    с минимумом, максимумом, средним и худшим уровнем тревоги в корзине.
    """
    # допуск 1e-6 корзины: julianday — double, отсчёт ровно на границе не уходит в прошлую корзину
    since = since.astimezone(_dt.timezone.utc)
    since_iso = since.isoformat(timespec="milliseconds")
    until_iso = until.astimezone(_dt.timezone.utc).isoformat(timespec="milliseconds") if until else None
    where_until = " AND timestamp <= :until" if until_iso else ""
    q_params: dict[str, Any] = {"cam": camera_id, "since": since_iso, "step": float(step_s)}
    if until_iso:
        q_params["until"] = until_iso
    async with _lock:
        conn = await _get_conn()
        cur = await conn.execute(
            f"""SELECT CAST((julianday(timestamp) - julianday(:since)) * 86400.0 / :step + 1e-6 AS INTEGER) AS b,
                       MIN(value) AS vmin, MAX(value) AS vmax, AVG(value) AS vavg, COUNT(*) AS n,
                       MAX(CASE status_level WHEN 'alert' THEN 2 WHEN 'warning' THEN 1 ELSE 0 END) AS lvl
                FROM readings
                WHERE camera_id = :cam AND timestamp >= :since{where_until} AND value IS NOT NULL
                GROUP BY b ORDER BY b""",
            q_params,
        )
        rows = await cur.fetchall()
    levels = ("normal", "warning", "alert")
    return [{"t": (since + _dt.timedelta(seconds=r["b"] * step_s)).isoformat(timespec="seconds"),
             "min": r["vmin"], "max": r["vmax"], "avg": r["vavg"], "n": r["n"],
             "level": levels[int(r["lvl"] or 0)]} for r in rows]


def _csv_safe_text(val: Any) -> str:
    """Защита строковых ячеек CSV от инъекции формул в табличных редакторах."""
    s = "" if val is None else str(val)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


async def export_csv(
    camera_id: str,
    limit: int = 1_000_000,
    *,
    since: str | None = None,
    until: str | None = None,
    run_id: str | None = None,
    demo_format: bool = False,
    instrument_id: str | None = None,
    source_kind: str = "phone_cv",
    unit_override: str | None = None,
) -> str:
    """Экспорт истории телеметрии в CSV (временные метки ISO 8601, UTC)."""
    cam = await get_camera(camera_id)
    default_unit = unit_override or (cam["unit"] if cam else "")
    history = await get_history(camera_id, limit, since=since, until=until, run_id=run_id)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    if demo_format:
        inst_code = _csv_safe_text(instrument_id or camera_id)
        src_txt = _csv_safe_text(source_kind)
        writer.writerow([
            "timestamp_iso8601", "instrument_id", "source_kind",
            "value", "unit", "raw_angle_deg", "status_level",
        ])
        for r in history:
            if r["value"] is None:
                continue
            row_unit = _csv_safe_text(r.get("unit") or default_unit)
            writer.writerow([
                r["timestamp"],
                inst_code,
                src_txt,
                f"{r['value']:.4f}",
                row_unit,
                "" if r["raw_angle"] is None else f"{r['raw_angle']:.2f}",
                r["status_level"],
            ])
    else:
        writer.writerow(["timestamp_iso8601", f"value_{_csv_safe_text(default_unit)}", "raw_angle_deg", "status_level"])
        for r in history:
            writer.writerow([
                r["timestamp"],
                "" if r["value"] is None else f"{r['value']:.4f}",
                "" if r["raw_angle"] is None else f"{r['raw_angle']:.2f}",
                r["status_level"],
            ])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Репозиторий: demo_runs (интервалы показа на защите)
# ---------------------------------------------------------------------------
def _row_to_run(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    for k in ("calibration", "thresholds"):
        try:
            d[k] = json.loads(d.get(k) or "{}")
        except json.JSONDecodeError:
            d[k] = {}
    return d


async def create_demo_run(
    *,
    camera_id: str,
    label: str | None = None,
    unit: str = "МПа",
    calibration: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    now = started_at or utcnow_iso()
    run_id = f"run-{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    async with _lock:
        conn = await _get_conn()
        # Завершаем открытые интервалы этой камеры, не удаляя их записи
        await conn.execute(
            "UPDATE demo_runs SET ended_at = ? WHERE camera_id = ? AND ended_at IS NULL",
            (now, camera_id),
        )
        cur = await conn.execute("SELECT COUNT(*) AS cnt FROM demo_runs WHERE camera_id = ?", (camera_id,))
        r_cnt = await cur.fetchone()
        idx = int(r_cnt["cnt"] if r_cnt else 0) + 1
        run_label = label or f"Показ №{idx}"
        await conn.execute(
            """INSERT INTO demo_runs
               (id, camera_id, label, started_at, ended_at, unit, calibration, thresholds, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                run_id, camera_id, run_label, now, None, unit,
                json.dumps(calibration or {}, ensure_ascii=False),
                json.dumps(thresholds or {}, ensure_ascii=False),
                now,
            ),
        )
        await conn.commit()
    return await get_demo_run(run_id)  # type: ignore[return-value]


async def finish_demo_run(run_id: str, ended_at: str | None = None) -> dict[str, Any] | None:
    end_ts = ended_at or utcnow_iso()
    async with _lock:
        conn = await _get_conn()
        await conn.execute(
            "UPDATE demo_runs SET ended_at = COALESCE(ended_at, ?) WHERE id = ?",
            (end_ts, run_id),
        )
        await conn.commit()
    return await get_demo_run(run_id)


async def update_demo_run_config(
    run_id: str,
    *,
    unit: str,
    calibration: dict[str, Any],
    thresholds: dict[str, Any],
    reset_start: bool = False,
) -> dict[str, Any] | None:
    now = utcnow_iso()
    async with _lock:
        conn = await _get_conn()
        if reset_start:
            await conn.execute(
                """UPDATE demo_runs
                   SET unit = ?, calibration = ?, thresholds = ?, started_at = ?
                   WHERE id = ?""",
                (
                    unit,
                    json.dumps(calibration, ensure_ascii=False),
                    json.dumps(thresholds, ensure_ascii=False),
                    now,
                    run_id,
                ),
            )
        else:
            await conn.execute(
                """UPDATE demo_runs
                   SET unit = ?, calibration = ?, thresholds = ?
                   WHERE id = ?""",
                (
                    unit,
                    json.dumps(calibration, ensure_ascii=False),
                    json.dumps(thresholds, ensure_ascii=False),
                    run_id,
                ),
            )
        await conn.commit()
    return await get_demo_run(run_id)


async def get_demo_run(run_id: str) -> dict[str, Any] | None:
    async with _lock:
        conn = await _get_conn()
        cur = await conn.execute(
            """SELECT r.*,
                      (SELECT COUNT(*) FROM readings rd
                       WHERE rd.camera_id = r.camera_id
                         AND rd.value IS NOT NULL
                         AND (rd.run_id = r.id OR (rd.run_id IS NULL AND rd.timestamp >= r.started_at
                              AND (r.ended_at IS NULL OR rd.timestamp <= r.ended_at)))) AS readings_count
               FROM demo_runs r WHERE r.id = ?""",
            (run_id,),
        )
        row = await cur.fetchone()
    return _row_to_run(row) if row else None


async def list_demo_runs(camera_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    where = "WHERE r.camera_id = ?" if camera_id else ""
    params: tuple[Any, ...] = (camera_id, int(limit)) if camera_id else (int(limit),)
    async with _lock:
        conn = await _get_conn()
        cur = await conn.execute(
            f"""SELECT r.*,
                       (SELECT COUNT(*) FROM readings rd
                        WHERE rd.camera_id = r.camera_id
                          AND rd.value IS NOT NULL
                          AND (rd.run_id = r.id OR (rd.run_id IS NULL AND rd.timestamp >= r.started_at
                               AND (r.ended_at IS NULL OR rd.timestamp <= r.ended_at)))) AS readings_count
                FROM demo_runs r {where}
                ORDER BY r.created_at DESC LIMIT ?""",
            params,
        )
        rows = await cur.fetchall()
    return [_row_to_run(r) for r in rows]


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
