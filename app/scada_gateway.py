"""
GaugeVision AI — Трек №2: Промышленный шлюз интеграции АСУ ТП (MQTT 3.1.1 и Modbus TCP).

Реализован без внешних сетевых библиотек (100% air-gapped ready на asyncio):
  • ModbusTcpGateway: карта Holding-регистров (HR 40001+) для всех 36 приборов
    (значение IEEE-754 float32 в 2 регистрах, IEEE-754 quiet NaN 0x7FC00000 при
    невалидных/устаревших показаниях, код состояния, Health Score ×10) + блок
    системной диагностики HR 40900+. Строгая валидация unit_id, FC 0x03/0x04 и
    диапазона регистров.
  • MqttAsyncAdapter: полная реализация MQTT 3.1.1 поверх asyncio TCP (+ TLS):
    CONNECT (username/password), PUBLISH QoS 1 с ожиданием PUBACK и DUP-повтором,
    поддержка QoS 0, PINGREQ/PINGRESP keepalive, таймауты и автопереподключение.
    При MQTT_ENABLED=True возвращает True ТОЛЬКО после подтверждённой доставки.
  • IdempotentReceiverLedger: реестр дедупликации по event_uuid на принимающей
    стороне для гарантии идемпотентной обработки при повторной доставке (at-least-once).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import ssl
import struct
import time
from collections import OrderedDict, deque
from typing import Any

from . import config
from .db import utcnow_iso

logger = logging.getLogger("gaugevision.scada")

_STATUS_TO_CODE = {"normal": 0, "warning": 1, "alert": 2, "stale": 3}
_IEEE754_QNAN_HI = 0x7FC0
_IEEE754_QNAN_LO = 0x0000


def _sanitize_json_obj(obj: Any) -> Any:
    """Гарантирует отсутствие NaN/Infinity в JSON-нагрузке SCADA/MQTT."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _sanitize_json_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json_obj(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Идемпотентный реестр принимающей стороны (дедупликация по event_uuid)
# ---------------------------------------------------------------------------
class IdempotentReceiverLedger:
    """
    Отслеживает уже принятые сквозные event_uuid (LRU-окно).
    При повторной доставке (потеря ACK / PUBACK) возвращает is_duplicate=True,
    исключая дублирующую обработку логического события.
    """

    def __init__(self, max_entries: int = 50_000) -> None:
        self._max = max(100, int(max_entries))
        self._seen: OrderedDict[str, str] = OrderedDict()
        self.accepted_unique: int = 0
        self.duplicates_ignored: int = 0

    def accept(self, event_uuid: str | None) -> bool:
        """Возвращает True для нового уникального event_uuid, False для дубликата."""
        if not event_uuid:
            self.accepted_unique += 1
            return True
        if event_uuid in self._seen:
            self._seen.move_to_end(event_uuid)
            self.duplicates_ignored += 1
            return False
        self._seen[event_uuid] = utcnow_iso()
        if len(self._seen) > self._max:
            self._seen.popitem(last=False)
        self.accepted_unique += 1
        return True

    def stats(self) -> dict[str, int]:
        return {
            "tracked_uuids": len(self._seen),
            "accepted_unique": self.accepted_unique,
            "duplicates_ignored": self.duplicates_ignored,
        }


# ---------------------------------------------------------------------------
# Pure-Python Modbus TCP Register Map & Async Server (FC 0x03 / 0x04)
# ---------------------------------------------------------------------------
class ModbusTcpGateway:
    """
    Карта Holding-регистров (40001+) для стыковки со SCADA (Ignition / MasterSCADA):
      Для каждого прибора (индекс idx = 0..199, базовый адрес addr = idx * 4):
        addr + 0, addr + 1 : IEEE-754 float32 (big-endian) — текущее значение (0x7FC00000 NaN при STALE/невалидном)
        addr + 2           : uint16 — статус (0=OK, 1=WARNING, 2=CRITICAL, 3=STALE)
        addr + 3           : uint16 — Health Score × 10 (0..1000)
      Системный диагностический блок (базовый адрес 900 -> HR 40901+):
        900 : всего приборов
        901 : активных аварий (CRITICAL)
        902 : активных предупреждений (WARNING)
        903 : каналов без данных (STALE)
        904 : записей в локальной очереди Store-and-Forward
        905 : флаг обрыва канала АСУ ТП (0=связь ок, 1=буферизация)
    """

    SYSTEM_BASE = 900
    MAX_REGISTERS = 1024
    MAX_SLOTS = 200

    def __init__(self) -> None:
        self._regs: list[int] = [0] * self.MAX_REGISTERS
        self._meta_rows: list[dict[str, Any]] = []
        self._server: asyncio.AbstractServer | None = None
        self._requests_served: int = 0
        self._rejected_unit_ids: int = 0
        self._active_clients: int = 0
        self._listening: bool = False
        self._last_error: str | None = None
        self._used_slots: set[int] = set()

    @classmethod
    def place_instruments(cls, instruments: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
        """Слот прибора (SHARED_DATA_CONTRACT § 5.3): постоянный modbus_slot из реестра; приборы без
        слота (симуляция стенда) занимают свободные слоты по порядку списка, как раньше."""
        placed: list[tuple[int, dict[str, Any]]] = []
        used: set[int] = set()
        rest: list[dict[str, Any]] = []
        for inst in instruments:
            slot = inst.get("modbus_slot")
            if isinstance(slot, int) and 0 <= slot < cls.MAX_SLOTS and slot not in used:
                placed.append((slot, inst))
                used.add(slot)
            else:
                rest.append(inst)
        free = (k for k in range(cls.MAX_SLOTS) if k not in used)
        for inst in rest:
            k = next(free, None)
            if k is None:
                break
            placed.append((k, inst))
        placed.sort(key=lambda t: t[0])
        return placed

    def update_from_instruments(
        self,
        instruments: list[dict[str, Any]],
        *,
        health_by_id: dict[str, float] | None = None,
        sf_pending: int = 0,
        outage_active: bool = False,
    ) -> None:
        hmap = health_by_id or {}
        rows: list[dict[str, Any]] = []
        crit_cnt = warn_cnt = stale_cnt = 0

        placed = self.place_instruments(instruments)
        for slot in self._used_slots - {k for k, _ in placed}:
            # прибор удалён: его слот больше не выдаёт последнее значение как достоверное
            b = slot * 4
            self._regs[b], self._regs[b + 1] = _IEEE754_QNAN_HI, _IEEE754_QNAN_LO
            self._regs[b + 2], self._regs[b + 3] = 3, 0
        self._used_slots = {k for k, _ in placed}
        for idx, inst in placed:
            base = idx * 4
            rd = inst.get("reading") or {}
            raw_v = rd.get("value")
            valid = bool(rd.get("valid")) and raw_v is not None
            val: float | None = None
            if valid:
                try:
                    f = float(raw_v)
                    if math.isfinite(f):
                        val = f
                    else:
                        valid = False
                except (TypeError, ValueError):
                    valid = False

            lv = (rd.get("level") or "normal") if valid else "stale"
            code = _STATUS_TO_CODE.get(lv, 3)
            if code == 2:
                crit_cnt += 1
            elif code == 1:
                warn_cnt += 1
            elif code == 3:
                stale_cnt += 1

            raw_hs = hmap.get(inst["id"], 100.0 if code == 0 else (72.0 if code == 1 else 42.0))
            try:
                hs = float(raw_hs)
                if not math.isfinite(hs):
                    hs = 0.0
            except (TypeError, ValueError):
                hs = 0.0
            hs_u16 = max(0, min(1000, int(round(hs * 10.0))))

            if valid and val is not None:
                hi, lo = struct.unpack(">HH", struct.pack(">f", val))
            else:
                # IEEE-754 quiet NaN (0x7FC00000): исключает путаницу невалидного датчика с нулевым значением 0.0
                hi, lo = _IEEE754_QNAN_HI, _IEEE754_QNAN_LO

            self._regs[base] = hi
            self._regs[base + 1] = lo
            self._regs[base + 2] = code
            self._regs[base + 3] = hs_u16

            rows.append({
                "instrument_id": inst["id"],
                "modbus_slot": idx,
                "code": inst.get("code") or inst["id"],
                "name": inst.get("short_name") or inst.get("name") or "",
                "unit": inst.get("unit") or "",
                "hr_value": 40001 + base,
                "hr_status": 40001 + base + 2,
                "hr_health": 40001 + base + 3,
                "value": round(val, 4) if (valid and val is not None) else None,
                "ieee754_nan": not valid,
                "raw_hi": hi,
                "raw_lo": lo,
                "status_code": code,
                "health_score": round(hs, 1),
            })

        self._regs[self.SYSTEM_BASE + 0] = min(65535, len(instruments))
        self._regs[self.SYSTEM_BASE + 1] = min(65535, crit_cnt)
        self._regs[self.SYSTEM_BASE + 2] = min(65535, warn_cnt)
        self._regs[self.SYSTEM_BASE + 3] = min(65535, stale_cnt)
        self._regs[self.SYSTEM_BASE + 4] = min(65535, max(0, int(sf_pending)))
        self._regs[self.SYSTEM_BASE + 5] = 1 if outage_active else 0
        self._meta_rows = rows

    async def start(self) -> None:
        if not config.MODBUS_ENABLED or self._server is not None:
            return
        try:
            self._server = await asyncio.start_server(
                self._handle_client, config.MODBUS_HOST, config.MODBUS_PORT
            )
            self._listening = True
            self._last_error = None
            logger.info("Modbus TCP сервер запущен на %s:%d (Unit ID %d)",
                        config.MODBUS_HOST, config.MODBUS_PORT, config.MODBUS_UNIT_ID)
        except OSError as exc:
            self._listening = False
            self._last_error = str(exc)
            logger.warning("Не удалось запустить Modbus TCP сервер: %s", exc)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._listening = False

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._active_clients += 1
        try:
            while True:
                mbap = await reader.readexactly(7)
                tx_id, proto_id, length, unit_id = struct.unpack(">HHHB", mbap)
                if proto_id != 0 or length < 2 or length > 256:
                    break
                pdu = await reader.readexactly(length - 1)
                fc = pdu[0]
                # Строгая проверка Unit ID (DEF-13): чужой unit_id отклоняется кодом 0x0B
                if unit_id != config.MODBUS_UNIT_ID:
                    self._rejected_unit_ids += 1
                    resp_pdu = struct.pack(">BB", fc | 0x80, 0x0B)  # Gateway Target Device Failed to Respond
                elif fc in (3, 4):
                    if len(pdu) != 5:
                        resp_pdu = struct.pack(">BB", fc | 0x80, 0x03)  # Illegal Data Value
                    else:
                        start_addr, count = struct.unpack(">HH", pdu[1:5])
                        if count < 1 or count > 125:
                            resp_pdu = struct.pack(">BB", fc | 0x80, 0x03)  # Illegal Data Value
                        elif start_addr + count > self.MAX_REGISTERS:
                            resp_pdu = struct.pack(">BB", fc | 0x80, 0x02)  # Illegal Data Address
                        else:
                            vals = self._regs[start_addr:start_addr + count]
                            payload = struct.pack(f">{count}H", *vals)
                            resp_pdu = struct.pack(">BB", fc, len(payload)) + payload
                            self._requests_served += 1
                else:
                    resp_pdu = struct.pack(">BB", fc | 0x80, 0x01)  # Illegal Function
                resp_mbap = struct.pack(">HHHB", tx_id, 0, len(resp_pdu) + 1, unit_id)
                writer.write(resp_mbap + resp_pdu)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._active_clients = max(0, self._active_clients - 1)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def status(self) -> dict[str, Any]:
        return {
            "enabled": config.MODBUS_ENABLED,
            "listening": self._listening,
            "host": config.MODBUS_HOST,
            "port": config.MODBUS_PORT,
            "unit_id": config.MODBUS_UNIT_ID,
            "registers_mapped": len(self._meta_rows) * 4 + 6,
            "requests_served": self._requests_served,
            "rejected_unit_ids": self._rejected_unit_ids,
            "active_clients": self._active_clients,
            "stale_encoding": "IEEE-754 NaN (0x7FC00000)",
            "last_error": self._last_error,
        }

    def registers_snapshot(self, limit: int = 36) -> dict[str, Any]:
        return {
            "status": self.status(),
            "system": {
                "HR40901_instruments_total": self._regs[self.SYSTEM_BASE + 0],
                "HR40902_active_critical": self._regs[self.SYSTEM_BASE + 1],
                "HR40903_active_warning": self._regs[self.SYSTEM_BASE + 2],
                "HR40904_stale_channels": self._regs[self.SYSTEM_BASE + 3],
                "HR40905_sf_queue_pending": self._regs[self.SYSTEM_BASE + 4],
                "HR40906_outage_flag": self._regs[self.SYSTEM_BASE + 5],
            },
            "instruments": self._meta_rows[:limit],
        }


# ---------------------------------------------------------------------------
# Pure-Python Async MQTT 3.1.1 Client Adapter (QoS 1 PUBACK, Auth, PINGREQ)
# ---------------------------------------------------------------------------
def _mqtt_encode_len(n: int) -> bytes:
    out = bytearray()
    while True:
        digit = n % 128
        n //= 128
        if n > 0:
            digit |= 0x80
        out.append(digit)
        if n == 0:
            break
    return bytes(out)


async def _mqtt_read_packet(reader: asyncio.StreamReader, timeout: float) -> tuple[int, bytes]:
    """Читает один полный пакет MQTT 3.1.1 с таймаутом. Возвращает (fixed_header_byte, body)."""
    hdr = await asyncio.wait_for(reader.readexactly(1), timeout=timeout)
    mult, rem_len = 1, 0
    for _ in range(4):
        b = (await asyncio.wait_for(reader.readexactly(1), timeout=timeout))[0]
        rem_len += (b & 0x7F) * mult
        if (b & 0x80) == 0:
            break
        mult *= 128
    else:
        raise ValueError("Malformed MQTT remaining length")
    body = await asyncio.wait_for(reader.readexactly(rem_len), timeout=timeout) if rem_len > 0 else b""
    return hdr[0], body


def _mqtt_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack(">H", len(b)) + b


def _build_mqtt_connect(
    client_id: str,
    *,
    keepalive: int = 30,
    username: str = "",
    password: str = "",
    clean_session: bool = True,
) -> bytes:
    flags = 0x02 if clean_session else 0x00
    payload = _mqtt_str(client_id)
    if username:
        flags |= 0x80
        payload += _mqtt_str(username)
        if password:
            flags |= 0x40
            payload += _mqtt_str(password)
    var_hdr = _mqtt_str("MQTT") + bytes([0x04, flags]) + struct.pack(">H", max(0, min(65535, int(keepalive))))
    body = var_hdr + payload
    return bytes([0x10]) + _mqtt_encode_len(len(body)) + body


def _build_mqtt_publish(
    topic: str,
    payload: bytes,
    *,
    qos: int = 1,
    packet_id: int | None = None,
    dup: bool = False,
) -> bytes:
    q = 1 if qos >= 1 else 0
    header_byte = 0x30 | ((1 if (dup and q == 1) else 0) << 3) | (q << 1)
    if q == 1:
        pid = int(packet_id or 1) & 0xFFFF
        if pid == 0:
            pid = 1
        body = _mqtt_str(topic) + struct.pack(">H", pid) + payload
    else:
        body = _mqtt_str(topic) + payload
    return bytes([header_byte]) + _mqtt_encode_len(len(body)) + body


_MQTT_PINGREQ = bytes([0xC0, 0x00])
_MQTT_DISCONNECT = bytes([0xE0, 0x00])


class MqttAsyncAdapter:
    """
    Асинхронный клиент MQTT 3.1.1:
      • CONNECT с поддержкой username/password и TLS;
      • PUBLISH с QoS 1 и обязательной проверкой PUBACK (или QoS 0 по конфигу);
      • PINGREQ / PINGRESP keepalive;
      • повторные попытки (DUP=1) и автопереподключение;
      • при MQTT_ENABLED=True publish() возвращает False при любой ошибке доставки.
    """

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected: bool = False
        self._published_total: int = 0
        self._broker_sent: int = 0
        self._puback_received: int = 0
        self._publish_failures: int = 0
        self._pings_ok: int = 0
        self._reconnects: int = 0
        self._next_pid: int = 1
        self._last_io_mono: float = 0.0
        self._last_error: str | None = None
        self._last_publish_at: str | None = None
        self._recent: deque[dict[str, Any]] = deque(maxlen=60)
        self._lock = asyncio.Lock()
        self._keepalive_task: asyncio.Task | None = None

    def _alloc_pid(self) -> int:
        pid = self._next_pid
        self._next_pid = (self._next_pid % 65535) + 1
        return pid

    async def connect(self) -> bool:
        if not config.MQTT_ENABLED:
            return False
        async with self._lock:
            return await self._connect_locked()

    async def _connect_locked(self) -> bool:
        if self._connected and self._writer is not None and not self._writer.is_closing():
            return True
        await self._close_locked()
        try:
            ssl_ctx = ssl.create_default_context() if config.MQTT_TLS else None
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(config.MQTT_HOST, config.MQTT_PORT, ssl=ssl_ctx),
                timeout=max(0.5, min(5.0, float(config.MQTT_ACK_TIMEOUT))),
            )
            pkt = _build_mqtt_connect(
                config.MQTT_CLIENT_ID,
                keepalive=config.MQTT_KEEPALIVE,
                username=config.MQTT_USERNAME,
                password=config.MQTT_PASSWORD,
            )
            self._writer.write(pkt)
            await self._writer.drain()
            hdr, body = await _mqtt_read_packet(self._reader, timeout=max(0.5, float(config.MQTT_ACK_TIMEOUT)))
            if (hdr >> 4) == 2 and len(body) >= 2 and body[1] == 0x00:
                self._connected = True
                self._last_io_mono = time.monotonic()
                self._last_error = None
                return True
            rc = body[1] if len(body) >= 2 else -1
            self._last_error = f"MQTT CONNACK rejected (rc={rc})"
        except Exception as exc:
            self._last_error = str(exc)
        await self._close_locked()
        return False

    async def _close_locked(self) -> None:
        self._connected = False
        if self._writer is not None:
            try:
                if not self._writer.is_closing():
                    self._writer.write(_MQTT_DISCONNECT)
                    await asyncio.wait_for(self._writer.drain(), timeout=0.3)
            except Exception:
                pass
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None

    async def start_keepalive(self) -> None:
        if config.MQTT_ENABLED and (self._keepalive_task is None or self._keepalive_task.done()):
            self._keepalive_task = asyncio.create_task(self._keepalive_loop(), name="mqtt-keepalive")

    async def _keepalive_loop(self) -> None:
        while True:
            try:
                interval = max(2.0, float(config.MQTT_KEEPALIVE) * 0.5)
                await asyncio.sleep(interval)
                if not config.MQTT_ENABLED:
                    continue
                if self._connected:
                    if time.monotonic() - self._last_io_mono >= max(1.0, float(config.MQTT_KEEPALIVE) * 0.6):
                        await self.ping()
                else:
                    ok = await self.connect()
                    if ok:
                        self._reconnects += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)

    async def ping(self) -> bool:
        """Отправляет MQTT PINGREQ (0xC0 0x00) и ожидает PINGRESP (0xD0 0x00)."""
        if not config.MQTT_ENABLED:
            return False
        async with self._lock:
            if not self._connected or self._writer is None or self._reader is None:
                return False
            try:
                self._writer.write(_MQTT_PINGREQ)
                await self._writer.drain()
                hdr, _ = await _mqtt_read_packet(self._reader, timeout=max(0.5, float(config.MQTT_ACK_TIMEOUT)))
                if (hdr >> 4) == 13:  # PINGRESP
                    self._pings_ok += 1
                    self._last_io_mono = time.monotonic()
                    return True
                self._last_error = f"Unexpected MQTT packet during PING: 0x{hdr:02x}"
            except Exception as exc:
                self._last_error = f"MQTT PINGREQ failed: {exc}"
            await self._close_locked()
            return False

    async def close(self) -> None:
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None
        async with self._lock:
            await self._close_locked()

    async def _send_publish_locked(self, topic: str, raw: bytes, qos: int, pid: int, dup: bool) -> bool:
        if not self._connected or self._writer is None or self._reader is None:
            return False
        pkt = _build_mqtt_publish(topic, raw, qos=qos, packet_id=pid, dup=dup)
        self._writer.write(pkt)
        await self._writer.drain()
        self._last_io_mono = time.monotonic()

        if qos == 0:
            return True

        # QoS 1: строго ждём PUBACK (0x40) с совпадающим Packet Identifier
        deadline = time.monotonic() + max(0.3, float(config.MQTT_ACK_TIMEOUT))
        while True:
            rem = deadline - time.monotonic()
            if rem <= 0:
                raise asyncio.TimeoutError(f"MQTT PUBACK timeout for pid={pid}")
            hdr, body = await _mqtt_read_packet(self._reader, timeout=rem)
            ptype = hdr >> 4
            if ptype == 4 and len(body) >= 2:  # PUBACK
                ack_pid = struct.unpack(">H", body[:2])[0]
                if ack_pid == pid:
                    self._puback_received += 1
                    self._last_io_mono = time.monotonic()
                    return True
            elif ptype == 13:  # PINGRESP — пропускаем и ждём свой PUBACK
                self._pings_ok += 1
                continue
            else:
                # Иные входящие пакеты в рамках таймаута игнорируем
                continue

    async def publish(
        self,
        subtopic: str,
        payload: dict[str, Any],
        *,
        seq_id: int | None = None,
        qos: int | None = None,
    ) -> bool:
        topic = f"{config.MQTT_TOPIC_PREFIX.rstrip('/')}/{subtopic.lstrip('/')}"
        clean_payload = _sanitize_json_obj(payload)
        raw = json.dumps(clean_payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        ts = utcnow_iso()
        eff_qos = int(config.MQTT_QOS if qos is None else qos)
        eff_qos = 1 if eff_qos >= 1 else 0
        sent_wire = False

        if config.MQTT_ENABLED:
            max_attempts = max(1, int(config.MQTT_MAX_RETRIES))
            pid = self._alloc_pid()
            for attempt in range(max_attempts):
                async with self._lock:
                    if not self._connected:
                        ok_conn = await self._connect_locked()
                        if ok_conn and attempt > 0:
                            self._reconnects += 1
                        if not ok_conn:
                            continue
                    try:
                        acked = await self._send_publish_locked(
                            topic, raw, qos=eff_qos, pid=pid, dup=(attempt > 0)
                        )
                        if acked:
                            sent_wire = True
                            self._broker_sent += 1
                            self._last_error = None
                            break
                    except Exception as exc:
                        self._last_error = str(exc)
                        await self._close_locked()

            if not sent_wire:
                self._publish_failures += 1
                # DEF-01: при MQTT_ENABLED=True НЕЛЬЗЯ возвращать True без подтверждённой доставки!
                return False

        self._published_total += 1
        self._last_publish_at = ts
        self._recent.append({
            "ts": ts,
            "seq_id": seq_id,
            "topic": topic,
            "bytes": len(raw),
            "qos": eff_qos if config.MQTT_ENABLED else 0,
            "wire_sent": sent_wire,
            "payload": clean_payload,
        })
        return True

    def status(self) -> dict[str, Any]:
        mode = "BROKER_LIVE" if (config.MQTT_ENABLED and self._connected) else (
            "BROKER_RETRY" if config.MQTT_ENABLED else "AIRGAPPED_LOCAL_BUS"
        )
        return {
            "enabled": config.MQTT_ENABLED,
            "mode": mode,
            "connected": self._connected,
            "broker": f"{config.MQTT_HOST}:{config.MQTT_PORT}",
            "tls": config.MQTT_TLS,
            "qos": 1 if config.MQTT_QOS >= 1 else 0,
            "auth_configured": bool(config.MQTT_USERNAME),
            "keepalive_s": config.MQTT_KEEPALIVE,
            "topic_prefix": config.MQTT_TOPIC_PREFIX,
            "published_total": self._published_total,
            "broker_sent": self._broker_sent,
            "puback_received": self._puback_received,
            "publish_failures": self._publish_failures,
            "pings_ok": self._pings_ok,
            "reconnects": self._reconnects,
            "last_publish_at": self._last_publish_at,
            "last_error": self._last_error,
        }

    def recent_messages(self, limit: int = 30) -> list[dict[str, Any]]:
        return list(reversed(self._recent))[:limit]


# ---------------------------------------------------------------------------
# Единый фасад SCADA-шлюза
# ---------------------------------------------------------------------------
class ScadaGateway:
    """Координирует доставку пачек Store-and-Forward в MQTT 3.1.1 и Modbus TCP с идемпотентностью."""

    def __init__(self) -> None:
        self.mqtt = MqttAsyncAdapter()
        self.modbus = ModbusTcpGateway()
        self.receiver_ledger = IdempotentReceiverLedger()
        self.batches_delivered: int = 0
        self.messages_delivered: int = 0
        self.frames_delivered: int = 0
        self.started_at = time.time()

    async def start(self) -> None:
        await self.modbus.start()
        if config.MQTT_ENABLED:
            await self.mqtt.connect()
            await self.mqtt.start_keepalive()

    async def stop(self) -> None:
        await self.modbus.stop()
        await self.mqtt.close()

    async def deliver_batch(self, items: list[dict[str, Any]]) -> bool:
        """
        Доставляет пачку сообщений в MQTT (и локальный инспектор).
        Возвращает False, если хотя бы одно сообщение не подтверждено брокером.
        Поддерживает передачу доказательных кадров frame_blob и идемпотентность по event_uuid.
        """
        delivered_in_batch = 0
        for item in items:
            ev_uuid = item.get("event_uuid")
            # Идемпотентная защита от повторной обработки при потере ACK/PUBACK (DEF-21)
            if not config.MQTT_ENABLED and not self.receiver_ledger.accept(ev_uuid):
                delivered_in_batch += 1
                continue

            ch = item.get("channel_id") or "station"
            ptype = item.get("payload_type") or "telemetry"
            payload: dict[str, Any] = {
                "seq_id": item.get("seq_id"),
                "event_uuid": ev_uuid,
                "edge_node": item.get("edge_node", config.EDGE_NODE_ID),
                "created_at": item.get("created_at"),
                "severity": item.get("severity", "info"),
                **(item.get("payload") or {}),
            }

            frame_blob: bytes | None = item.get("frame_blob")
            if isinstance(frame_blob, (bytes, bytearray)) and len(frame_blob) > 0:
                sha = item.get("frame_sha256") or hashlib.sha256(frame_blob).hexdigest()
                payload["has_frame"] = True
                payload["frame_sha256"] = sha
                payload["frame_bytes"] = len(frame_blob)

            ok = await self.mqtt.publish(f"{ch}/{ptype}", payload, seq_id=item.get("seq_id"))
            if not ok:
                return False

            # Если к событию приложен доказательный кадр (DEF-06) — передаём его отдельным сообщением frame
            if isinstance(frame_blob, (bytes, bytearray)) and len(frame_blob) > 0:
                sha = item.get("frame_sha256") or hashlib.sha256(frame_blob).hexdigest()
                frame_msg = {
                    "seq_id": item.get("seq_id"),
                    "event_uuid": ev_uuid,
                    "edge_node": item.get("edge_node", config.EDGE_NODE_ID),
                    "created_at": item.get("created_at"),
                    "frame_sha256": sha,
                    "frame_bytes": len(frame_blob),
                    "frame_b64": base64.b64encode(bytes(frame_blob)).decode("ascii"),
                }
                ok_frm = await self.mqtt.publish(f"{ch}/frame", frame_msg, seq_id=item.get("seq_id"))
                if not ok_frm:
                    return False
                self.frames_delivered += 1

            if config.MQTT_ENABLED:
                self.receiver_ledger.accept(ev_uuid)
            delivered_in_batch += 1

        self.batches_delivered += 1
        self.messages_delivered += delivered_in_batch
        return True

    def status(self) -> dict[str, Any]:
        return {
            "edge_node": config.EDGE_NODE_ID,
            "batches_delivered": self.batches_delivered,
            "messages_delivered": self.messages_delivered,
            "frames_delivered": self.frames_delivered,
            "idempotency": self.receiver_ledger.stats(),
            "mqtt": self.mqtt.status(),
            "modbus": self.modbus.status(),
        }
