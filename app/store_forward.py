"""
GaugeVision AI — Трек №2: Локальный персистентный буфер Store-and-Forward (SQLite WAL).

Обеспечивает гарантированную доставку телеметрии, событий и доказательных кадров
в условиях нестабильной промышленной сети («Edge-узел → центральный контур АСУ ТП»):
  • SQLite в режиме WAL (`PRAGMA journal_mode=WAL`) — фактический режим проверяется
    напрямую через PRAGMA, транзакционная фиксация пачек (sf_queue + sf_batches);
  • сквозной монотонный `seq_id`, глобальный `event_uuid` и SHA-256 контроль
    целостности доказательных кадров `frame_blob`;
  • фактическая передача `frame_blob` в `deliver_cb` при штатной отправке и досылке;
  • строгий хронологический порядок (`ORDER BY seq_id ASC`);
  • ограничение очереди по числу записей (`SF_MAX_QUEUE_ROWS`), объёму pending
    (`SF_MAX_PENDING_MB`) и свободному месту на диске (`SF_MIN_DISK_FREE_MB`) с
    явной политикой вытеснения низкоприоритетной телеметрии, приоритетом сохранения
    `alarm`/`frame` и обязательной диагностикой переполнения (`sf_overflow_log`,
    `queue_overflow`, `evicted_total`) — без тихой потери данных;
  • учёт `retry_count` и exponential backoff при ошибках доставки + опциональный
    реестр идемпотентной обработки (`IdempotentDeliveryStore`).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import shutil
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiosqlite

from . import config
from .db import utcnow_iso

logger = logging.getLogger("gaugevision.store_forward")

DeliverCallback = Callable[[list[dict[str, Any]]], Awaitable[bool]]

SF_SCHEMA = """
CREATE TABLE IF NOT EXISTS sf_queue (
    seq_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uuid    TEXT NOT NULL UNIQUE,
    edge_node     TEXT NOT NULL,
    channel_id    TEXT NOT NULL,
    payload_type  TEXT NOT NULL CHECK (payload_type IN ('telemetry','alarm','frame','health')),
    severity      TEXT NOT NULL DEFAULT 'info',
    priority      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    frame_blob    BLOB,
    frame_sha256  TEXT,
    size_bytes    INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent')),
    retry_count   INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    batch_id      TEXT,
    sent_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_sf_status_seq ON sf_queue (status, seq_id);
CREATE INDEX IF NOT EXISTS idx_sf_channel ON sf_queue (channel_id, seq_id);
CREATE INDEX IF NOT EXISTS idx_sf_priority_seq ON sf_queue (status, priority, seq_id);

CREATE TABLE IF NOT EXISTS sf_batches (
    batch_id     TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    items_count  INTEGER NOT NULL,
    bytes_sent   INTEGER NOT NULL,
    frames_sent  INTEGER NOT NULL DEFAULT 0,
    target       TEXT NOT NULL,
    status       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sf_overflow_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    reason        TEXT NOT NULL,
    evicted_count INTEGER NOT NULL,
    evicted_bytes INTEGER NOT NULL,
    pending_after INTEGER NOT NULL
);
"""


def _sanitize_json(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    return obj


class StoreAndForwardBuffer:
    """Асинхронная персистентная очередь Store-and-Forward на базе SQLite WAL."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._explicit_path = db_path
        self._lock = asyncio.Lock()
        self._conn: aiosqlite.Connection | None = None
        self._journal_mode: str = "unknown"
        self._outage_active: bool = False
        self._outage_since: str | None = None
        self._outage_reason: str | None = None
        self._syncing: bool = False
        self._delivered_total: int = 0
        self._buffered_during_outage: int = 0
        self._evicted_total: int = 0
        self._rejected_overflow_total: int = 0
        self._queue_overflow: bool = False
        self._overflow_reason: str | None = None
        self._retry_backoff_until: float = 0.0
        self._consecutive_delivery_fails: int = 0
        self._last_sync_at: str | None = None
        self._last_batch_size: int = 0
        self._deliver_cb: DeliverCallback | None = None
        self._on_change: Callable[[dict[str, Any]], None] | None = None
        self._recent_batches: deque[dict[str, Any]] = deque(maxlen=20)
        self._task: asyncio.Task | None = None

    @property
    def db_path(self) -> Path:
        return self._explicit_path or config.get_sf_db_path()

    def configure(self, *, deliver_cb: DeliverCallback | None = None,
                  on_change: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._deliver_cb = deliver_cb
        self._on_change = on_change

    async def init(self) -> None:
        async with self._lock:
            if self._conn is not None:
                return
            path = self.db_path
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(str(path), timeout=30)
            self._conn.row_factory = aiosqlite.Row
            cur_jm = await self._conn.execute("PRAGMA journal_mode=WAL")
            row_jm = await cur_jm.fetchone()
            self._journal_mode = str(row_jm[0]).lower() if row_jm else "unknown"
            await self._conn.execute("PRAGMA synchronous=NORMAL")
            await self._conn.executescript(SF_SCHEMA)
            await self._migrate_schema_locked()
            await self._conn.commit()
            cur = await self._conn.execute("SELECT COUNT(*) AS n FROM sf_queue WHERE status = 'sent'")
            row = await cur.fetchone()
            self._delivered_total = int(row["n"] if row else 0)
            cur_ov = await self._conn.execute("SELECT COALESCE(SUM(evicted_count), 0) AS n FROM sf_overflow_log")
            row_ov = await cur_ov.fetchone()
            self._evicted_total = int(row_ov["n"] if row_ov else 0)
            cur_b = await self._conn.execute(
                "SELECT * FROM sf_batches ORDER BY completed_at DESC LIMIT 12"
            )
            for b in reversed(await cur_b.fetchall()):
                self._recent_batches.append(dict(b))

    async def _migrate_schema_locked(self) -> None:
        """Безопасная миграция существующих БД без потери накопленных данных."""
        assert self._conn is not None
        cur = await self._conn.execute("PRAGMA table_info(sf_queue)")
        cols = {r["name"] for r in await cur.fetchall()}
        if "priority" not in cols:
            await self._conn.execute("ALTER TABLE sf_queue ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
        if "frame_sha256" not in cols:
            await self._conn.execute("ALTER TABLE sf_queue ADD COLUMN frame_sha256 TEXT")
        if "retry_count" not in cols:
            await self._conn.execute("ALTER TABLE sf_queue ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
        if "last_error" not in cols:
            await self._conn.execute("ALTER TABLE sf_queue ADD COLUMN last_error TEXT")

        cur_b = await self._conn.execute("PRAGMA table_info(sf_batches)")
        bcols = {r["name"] for r in await cur_b.fetchall()}
        if "frames_sent" not in bcols:
            await self._conn.execute("ALTER TABLE sf_batches ADD COLUMN frames_sent INTEGER NOT NULL DEFAULT 0")

    async def start(self) -> None:
        await self.init()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._sync_loop(), name="sf-sync-loop")

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        async with self._lock:
            if self._conn is not None:
                try:
                    await self._conn.close()
                finally:
                    self._conn = None

    @property
    def outage_active(self) -> bool:
        return self._outage_active

    def _disk_free_mb(self) -> float:
        try:
            usage = shutil.disk_usage(str(self.db_path.parent))
            return round(usage.free / (1024.0 * 1024.0), 1)
        except OSError:
            return -1.0

    async def set_outage(self, active: bool, reason: str = "Симуляция обрыва канала АСУ ТП") -> dict[str, Any]:
        active = bool(active)
        changed = active != self._outage_active
        self._outage_active = active
        if active:
            self._outage_since = utcnow_iso()
            self._outage_reason = reason
            self._buffered_during_outage = 0
            logger.warning("Store-and-Forward: активирован режим автономной буферизации (%s)", reason)
        else:
            self._outage_since = None
            self._outage_reason = None
            self._retry_backoff_until = 0.0
            self._consecutive_delivery_fails = 0
            logger.info("Store-and-Forward: связь с верхним уровнем восстановлена — запуск досылки пачками")
            if changed:
                asyncio.create_task(self.flush_pending(max_batches=25), name="sf-recover-flush")
        st = await self.stats()
        if self._on_change:
            self._on_change(st)
        return st

    async def _enforce_quota_locked(self, incoming_priority: int, incoming_bytes: int) -> tuple[bool, str | None]:
        """
        Политика ограничения очереди (DEF-06):
          1. Сначала очищает старые уже отправленные (`status='sent'`) записи сверх лимита.
          2. Проверяет свободное место на диске (`SF_MIN_DISK_FREE_MB`).
          3. Проверяет лимит pending по количеству (`SF_MAX_QUEUE_ROWS`) и объёму (`SF_MAX_PENDING_MB`).
          4. При превышении вытесняет самые старые низкоприоритетные `telemetry` записи с
             приоритетом сохранения `alarm`/`frame`/`health` и записью в `sf_overflow_log`.
          5. Если очередь целиком заполнена критическими событиями — НЕ удаляет их молча,
             а возвращает `(False, reason)` с явной диагностикой переполнения.
        """
        assert self._conn is not None
        max_rows = max(1, int(config.SF_MAX_QUEUE_ROWS))
        max_bytes = max(4096, int(float(config.SF_MAX_PENDING_MB) * 1024 * 1024))

        # 1. Очистка старых доставленных записей
        await self._conn.execute(
            """DELETE FROM sf_queue WHERE status = 'sent' AND seq_id < (
                   SELECT COALESCE(MAX(seq_id), 0) - ? FROM sf_queue
               )""",
            (max_rows,),
        )

        # 2. Проверка свободного места на диске
        free_mb = self._disk_free_mb()
        if 0 <= free_mb < float(config.SF_MIN_DISK_FREE_MB):
            self._queue_overflow = True
            self._overflow_reason = f"Недостаточно места на диске ({free_mb:.1f} МБ < {config.SF_MIN_DISK_FREE_MB:.0f} МБ)"
            if incoming_priority == 0:
                self._rejected_overflow_total += 1
                return False, self._overflow_reason

        # 3. Проверка pending по числу строк и байт
        cur = await self._conn.execute(
            """SELECT COUNT(*) AS cnt, COALESCE(SUM(size_bytes), 0) AS total_b
               FROM sf_queue WHERE status = 'pending'"""
        )
        row = await cur.fetchone()
        pending_cnt = int(row["cnt"] if row else 0)
        pending_bytes = int(row["total_b"] if row else 0)

        need_free_rows = max(0, (pending_cnt + 1) - max_rows)
        need_free_bytes = max(0, (pending_bytes + incoming_bytes) - max_bytes)
        if need_free_rows == 0 and need_free_bytes == 0:
            return True, None

        # 4. Вытесняем самые старые низкоприоритетные telemetry-записи (priority = 0)
        cur_cand = await self._conn.execute(
            """SELECT seq_id, size_bytes FROM sf_queue
               WHERE status = 'pending' AND priority = 0
               ORDER BY seq_id ASC
               LIMIT ?""",
            (max(need_free_rows, 50),),
        )
        cands = await cur_cand.fetchall()
        evict_ids: list[int] = []
        evict_bytes = 0
        for c in cands:
            evict_ids.append(int(c["seq_id"]))
            evict_bytes += int(c["size_bytes"] or 0)
            if len(evict_ids) >= need_free_rows and evict_bytes >= need_free_bytes:
                break

        if evict_ids:
            ph = ",".join("?" for _ in evict_ids)
            await self._conn.execute(f"DELETE FROM sf_queue WHERE seq_id IN ({ph})", evict_ids)
            self._evicted_total += len(evict_ids)
            self._queue_overflow = True
            reason = (
                f"Переполнение очереди pending (лимит {max_rows} зап. / {config.SF_MAX_PENDING_MB:.0f} МБ): "
                f"вытеснено {len(evict_ids)} старых записей телеметрии с сохранением тревог"
            )
            self._overflow_reason = reason
            await self._conn.execute(
                """INSERT INTO sf_overflow_log (ts, reason, evicted_count, evicted_bytes, pending_after)
                   VALUES (?,?,?,?,?)""",
                (utcnow_iso(), reason, len(evict_ids), evict_bytes, max(0, pending_cnt - len(evict_ids))),
            )
            logger.warning("Store-and-Forward: %s", reason)

            # Перепроверяем, хватило ли места после вытеснения telemetry
            if (pending_cnt - len(evict_ids) + 1) <= max_rows and (pending_bytes - evict_bytes + incoming_bytes) <= max_bytes:
                return True, None

        # 5. Если всё занято критическими alarm/frame — не удаляем их молча
        self._queue_overflow = True
        self._overflow_reason = (
            f"Очередь переполнена критическими событиями (лимит {max_rows} зап.): "
            f"дальнейшее накопление невозможно до восстановления связи"
        )
        self._rejected_overflow_total += 1
        logger.error("Store-and-Forward: %s", self._overflow_reason)
        return False, self._overflow_reason

    async def enqueue(
        self,
        *,
        channel_id: str,
        payload_type: str,
        payload: dict[str, Any],
        severity: str = "info",
        frame_blob: bytes | None = None,
    ) -> dict[str, Any]:
        """
        Добавляет сообщение в персистентную очередь WAL с присвоением сквозного seq_id.
        Если канал вверх активен — сразу доставляет и помечает sent; при обрыве или
        отказе транспорта — оставляет pending.
        """
        await self.init()
        ts = utcnow_iso()
        ev_uuid = str(uuid.uuid4())
        clean_payload = _sanitize_json(payload)
        body = json.dumps(clean_payload, ensure_ascii=False, allow_nan=False)
        blob = bytes(frame_blob) if frame_blob else None
        frame_sha = hashlib.sha256(blob).hexdigest() if blob else None
        size_bytes = len(body.encode("utf-8")) + (len(blob) if blob else 0)
        priority = 1 if payload_type in ("alarm", "frame", "health") or severity in ("alert", "warning") else 0

        async with self._lock:
            assert self._conn is not None
            can_accept, reject_reason = await self._enforce_quota_locked(priority, size_bytes)
            if not can_accept:
                await self._conn.commit()
                return {
                    "seq_id": None,
                    "event_uuid": ev_uuid,
                    "status": "rejected_overflow",
                    "size_bytes": size_bytes,
                    "overflow": True,
                    "reason": reject_reason,
                }
            cur = await self._conn.execute(
                """INSERT INTO sf_queue
                   (event_uuid, edge_node, channel_id, payload_type, severity, priority,
                    created_at, payload_json, frame_blob, frame_sha256, size_bytes, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending')""",
                (ev_uuid, config.EDGE_NODE_ID, channel_id, payload_type, severity, priority,
                 ts, body, blob, frame_sha, size_bytes),
            )
            seq_id = int(cur.lastrowid or 0)
            await self._conn.commit()

        if self._outage_active:
            self._buffered_during_outage += 1
            return {
                "seq_id": seq_id,
                "event_uuid": ev_uuid,
                "status": "pending",
                "size_bytes": size_bytes,
                "overflow": self._queue_overflow,
            }

        # Штатный режим: проверяем, нет ли накопленного хвоста и не идёт ли sync, чтобы не нарушать хронологию
        pending_now = await self.pending_count()
        if pending_now <= 1 and not self._syncing:
            delivered = await self._deliver_items([{
                "seq_id": seq_id,
                "event_uuid": ev_uuid,
                "edge_node": config.EDGE_NODE_ID,
                "channel_id": channel_id,
                "payload_type": payload_type,
                "severity": severity,
                "created_at": ts,
                "payload": clean_payload,
                "size_bytes": size_bytes,
                "has_frame": blob is not None,
                "frame_blob": blob,
                "frame_sha256": frame_sha,
                "retry_count": 0,
            }])
            if delivered:
                await self._mark_sent([seq_id], batch_id="live", sent_at=utcnow_iso())
                return {"seq_id": seq_id, "event_uuid": ev_uuid, "status": "sent", "size_bytes": size_bytes}
            await self._record_retry([seq_id], error="delivery_failed")
        return {"seq_id": seq_id, "event_uuid": ev_uuid, "status": "pending", "size_bytes": size_bytes}

    async def _deliver_items(self, items: list[dict[str, Any]]) -> bool:
        if self._outage_active:
            return False
        if self._deliver_cb is None:
            return True
        try:
            ok = bool(await self._deliver_cb(items))
            if ok:
                self._consecutive_delivery_fails = 0
                self._retry_backoff_until = 0.0
            else:
                self._consecutive_delivery_fails += 1
            return ok
        except Exception as exc:
            self._consecutive_delivery_fails += 1
            logger.warning("Store-and-Forward delivery error: %s", exc)
            return False

    async def _record_retry(self, seq_ids: list[int], *, error: str) -> None:
        if not seq_ids:
            return
        placeholders = ",".join("?" for _ in seq_ids)
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute(
                f"UPDATE sf_queue SET retry_count = retry_count + 1, last_error = ? WHERE seq_id IN ({placeholders})",
                [error[:240], *seq_ids],
            )
            await self._conn.commit()

    async def _mark_sent(self, seq_ids: list[int], *, batch_id: str, sent_at: str,
                         batch_record: dict[str, Any] | None = None) -> None:
        if not seq_ids:
            return
        placeholders = ",".join("?" for _ in seq_ids)
        async with self._lock:
            assert self._conn is not None
            # Атомарная транзакция: обновление sf_queue и запись sf_batches коммитятся вместе
            await self._conn.execute(
                f"UPDATE sf_queue SET status = 'sent', batch_id = ?, sent_at = ?, last_error = NULL WHERE seq_id IN ({placeholders})",
                [batch_id, sent_at, *seq_ids],
            )
            if batch_record is not None:
                await self._conn.execute(
                    """INSERT INTO sf_batches
                       (batch_id, started_at, completed_at, items_count, bytes_sent, frames_sent, target, status)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        batch_record["batch_id"], batch_record["started_at"], batch_record["completed_at"],
                        batch_record["items_count"], batch_record["bytes_sent"], batch_record["frames_sent"],
                        batch_record["target"], batch_record["status"],
                    ),
                )
            await self._conn.commit()
        self._delivered_total += len(seq_ids)
        self._last_sync_at = sent_at

    async def pending_count(self) -> int:
        await self.init()
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute("SELECT COUNT(*) AS n FROM sf_queue WHERE status = 'pending'")
            row = await cur.fetchone()
            return int(row["n"] if row else 0)

    async def flush_pending(self, max_batches: int = 5) -> dict[str, Any]:
        """Досылает накопленные записи пачками в строгом хронологическом порядке (ORDER BY seq_id ASC)."""
        await self.init()
        if self._outage_active:
            return {"flushed": 0, "batches": 0, "reason": "outage_active"}
        if self._syncing:
            return {"flushed": 0, "batches": 0, "reason": "already_syncing"}

        self._syncing = True
        total_flushed = 0
        batches_done = 0
        try:
            for _ in range(max_batches):
                if self._outage_active:
                    break
                async with self._lock:
                    assert self._conn is not None
                    cur = await self._conn.execute(
                        """SELECT seq_id, event_uuid, edge_node, channel_id, payload_type,
                                  severity, created_at, payload_json, frame_blob, frame_sha256,
                                  size_bytes, retry_count
                           FROM sf_queue
                           WHERE status = 'pending'
                           ORDER BY seq_id ASC
                           LIMIT ?""",
                        (config.SF_BATCH_SIZE,),
                    )
                    rows = await cur.fetchall()
                if not rows:
                    if self._queue_overflow:
                        self._queue_overflow = False
                        self._overflow_reason = None
                    break

                started_at = utcnow_iso()
                batch_id = f"batch-{int(time.time())}-{uuid.uuid4().hex[:6]}"
                items: list[dict[str, Any]] = []
                seq_ids: list[int] = []
                bytes_sent = 0
                frames_sent = 0
                for r in rows:
                    seq_ids.append(int(r["seq_id"]))
                    bytes_sent += int(r["size_bytes"] or 0)
                    try:
                        parsed = json.loads(r["payload_json"])
                    except json.JSONDecodeError:
                        parsed = {}
                    raw_blob = r["frame_blob"]
                    blob: bytes | None = bytes(raw_blob) if raw_blob is not None else None
                    stored_sha = r["frame_sha256"]
                    integrity_ok = True
                    if blob is not None:
                        actual_sha = hashlib.sha256(blob).hexdigest()
                        if stored_sha and actual_sha != stored_sha:
                            integrity_ok = False
                            logger.error("Store-and-Forward: нарушение целостности frame_blob для seq_id=%s", r["seq_id"])
                        else:
                            stored_sha = stored_sha or actual_sha
                        frames_sent += 1
                    items.append({
                        "seq_id": int(r["seq_id"]),
                        "event_uuid": r["event_uuid"],
                        "edge_node": r["edge_node"],
                        "channel_id": r["channel_id"],
                        "payload_type": r["payload_type"],
                        "severity": r["severity"],
                        "created_at": r["created_at"],
                        "payload": parsed,
                        "size_bytes": int(r["size_bytes"] or 0),
                        "has_frame": blob is not None,
                        "frame_blob": blob,
                        "frame_sha256": stored_sha,
                        "frame_integrity_ok": integrity_ok,
                        "retry_count": int(r["retry_count"] or 0),
                    })

                ok = await self._deliver_items(items)
                if not ok:
                    await self._record_retry(seq_ids, error="batch_delivery_failed")
                    delay = min(30.0, 0.5 * (2 ** min(self._consecutive_delivery_fails, 6)))
                    self._retry_backoff_until = time.monotonic() + delay
                    break

                completed_at = utcnow_iso()
                rec = {
                    "batch_id": batch_id,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "items_count": len(seq_ids),
                    "bytes_sent": bytes_sent,
                    "frames_sent": frames_sent,
                    "target": "SCADA / MQTT / Central",
                    "status": "delivered",
                }
                await self._mark_sent(seq_ids, batch_id=batch_id, sent_at=completed_at, batch_record=rec)
                self._recent_batches.append(rec)
                self._last_batch_size = len(seq_ids)
                total_flushed += len(seq_ids)
                batches_done += 1
                if self._on_change:
                    self._on_change(await self.stats())
                # Межпачечная пауза настраивается (по умолчанию 0.0 — максимальная скорость досылки, DEF-19)
                if config.SF_BATCH_DELAY_S > 0 and len(seq_ids) >= config.SF_BATCH_SIZE:
                    await asyncio.sleep(config.SF_BATCH_DELAY_S)
        finally:
            self._syncing = False
        return {"flushed": total_flushed, "batches": batches_done}

    async def _sync_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(config.SF_SYNC_INTERVAL)
                if not self._outage_active and time.monotonic() >= self._retry_backoff_until:
                    await self.flush_pending(max_batches=3)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Store-and-Forward sync loop: %s", exc)

    async def stats(self, recent_limit: int = 12) -> dict[str, Any]:
        await self.init()
        async with self._lock:
            assert self._conn is not None
            cur = await self._conn.execute(
                """SELECT
                       SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_cnt,
                       COALESCE(SUM(CASE WHEN status = 'pending' THEN size_bytes ELSE 0 END), 0) AS pending_bytes,
                       SUM(CASE WHEN status = 'pending' AND priority > 0 THEN 1 ELSE 0 END) AS pending_alarms,
                       SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) AS sent_cnt,
                       COALESCE(MAX(retry_count), 0) AS max_retries,
                       MAX(seq_id) AS last_seq
                   FROM sf_queue"""
            )
            agg = await cur.fetchone()
            cur_q = await self._conn.execute(
                """SELECT seq_id, event_uuid, channel_id, payload_type, severity,
                          created_at, size_bytes, status, retry_count, batch_id, sent_at,
                          (frame_blob IS NOT NULL) AS has_frame
                   FROM sf_queue
                   ORDER BY seq_id DESC
                   LIMIT ?""",
                (recent_limit,),
            )
            recent_items = [dict(r) for r in await cur_q.fetchall()]

        pending_cnt = int((agg["pending_cnt"] if agg else 0) or 0)
        pending_bytes = int((agg["pending_bytes"] if agg else 0) or 0)
        pending_alarms = int((agg["pending_alarms"] if agg else 0) or 0)
        sent_cnt = int((agg["sent_cnt"] if agg else 0) or 0)
        max_retries = int((agg["max_retries"] if agg else 0) or 0)
        last_seq = int((agg["last_seq"] if agg else 0) or 0)

        db_bytes = 0
        for p in (self.db_path, Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm")):
            try:
                if p.exists():
                    db_bytes += os.path.getsize(p)
            except OSError:
                pass

        if self._outage_active:
            sync_state = "BUFFERING"
        elif self._syncing or pending_cnt > 0:
            sync_state = "SYNCING"
        else:
            sync_state = "CONNECTED"

        return {
            "edge_node": config.EDGE_NODE_ID,
            "sync_state": sync_state,
            "outage_active": self._outage_active,
            "outage_since": self._outage_since,
            "outage_reason": self._outage_reason,
            "pending_count": pending_cnt,
            "pending_alarms": pending_alarms,
            "pending_bytes": pending_bytes,
            "pending_kb": round(pending_bytes / 1024.0, 2),
            "pending_mb": round(pending_bytes / (1024.0 * 1024.0), 4),
            "delivered_total": max(sent_cnt, self._delivered_total),
            "last_seq_id": last_seq,
            "buffered_during_outage": self._buffered_during_outage,
            "queue_overflow": self._queue_overflow,
            "overflow_reason": self._overflow_reason,
            "evicted_total": self._evicted_total,
            "rejected_overflow_total": self._rejected_overflow_total,
            "max_queue_rows": config.SF_MAX_QUEUE_ROWS,
            "max_pending_mb": config.SF_MAX_PENDING_MB,
            "disk_free_mb": self._disk_free_mb(),
            "max_retries": max_retries,
            "last_sync_at": self._last_sync_at,
            "last_batch_size": self._last_batch_size,
            "db_size_mb": round(db_bytes / (1024.0 * 1024.0), 3),
            "journal_mode": self._journal_mode,
            "wal_mode": self._journal_mode == "wal",
            "batch_size": config.SF_BATCH_SIZE,
            "recent_batches": list(reversed(self._recent_batches))[:10],
            "recent_items": recent_items,
        }
