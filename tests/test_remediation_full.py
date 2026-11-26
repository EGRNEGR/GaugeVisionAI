"""
Комплексный регрессионный, интеграционный и security-набор тестов устранения
дефектов DEF-01 — DEF-22 проекта GaugeVision AI (строго CPU-only).

Запуск:
  CUDA_VISIBLE_DEVICES="" GAUGEVISION_DEVICE=cpu python -B tests/test_remediation_full.py
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import io
import json
import math
import os
import sqlite3
import struct
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"
os.environ["GAUGEVISION_DEMO"] = "1"
os.environ["GAUGEVISION_AUTH_REQUIRED"] = "1"
os.environ["GAUGEVISION_MODBUS_ENABLED"] = "1"
os.environ["GAUGEVISION_MODBUS_PORT"] = "15522"
os.environ["GAUGEVISION_STALE_SECONDS"] = "2.5"

_TMP = Path(tempfile.mkdtemp(prefix="gv_remediation_full_"))
os.environ["GAUGEVISION_DB"] = str(_TMP / "main.db")
os.environ["GAUGEVISION_SF_DB"] = str(_TMP / "sf.db")
os.environ["GAUGEVISION_INCIDENTS_DIR"] = str(_TMP / "incidents")
os.environ["GAUGEVISION_AUTO_SPECS_DIR"] = str(_TMP / "auto_specs")
os.environ["GAUGEVISION_VIDEOS_DIR"] = str(_TMP / "videos")
os.environ["YOLO_CONFIG_DIR"] = str(_TMP / "yolo_cfg")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, vision  # noqa: E402
from app.dispatch_analyzer import DispatchAnalyzer  # noqa: E402
from app.scada_gateway import MqttAsyncAdapter, ModbusTcpGateway, ScadaGateway  # noqa: E402
from app.spec_generator import LEGAL_DISCLAIMER, generate_spec_bundle, render_spec_docx  # noqa: E402
from app.store_forward import StoreAndForwardBuffer  # noqa: E402
from app.stream_manager import (  # noqa: E402
    AdaptiveFpsController,
    FrameQualityAnalyzer,
    IncidentRingBuffer,
    render_gauge_frame,
)

RESULTS: list[dict[str, Any]] = []


def record_case(name: str, defects: list[str], fn) -> None:
    t0 = time.perf_counter()
    try:
        details = fn()
        dt = round((time.perf_counter() - t0) * 1000.0, 1)
        RESULTS.append({"name": name, "defects": defects, "passed": True, "ms": dt, "details": details or {}})
        print(f"[PASS] {name} ({','.join(defects)}) — {dt} ms")
    except Exception as exc:
        dt = round((time.perf_counter() - t0) * 1000.0, 1)
        RESULTS.append({"name": name, "defects": defects, "passed": False, "ms": dt, "error": f"{type(exc).__name__}: {exc}"})
        print(f"[FAIL] {name} ({','.join(defects)}) — {type(exc).__name__}: {exc}")
        raise


# ---------------------------------------------------------------------------
# Локальный MQTT 3.1.1 QoS 1 брокер (поддерживает CONNECT Auth, PUBACK,
# сброс PUBACK по запросу, PINGREQ/PINGRESP, аварийное отключение)
# ---------------------------------------------------------------------------
class MockMqttQoS1Broker:
    def __init__(self, expected_user: str | None = None, expected_pass: str | None = None) -> None:
        self.expected_user = expected_user
        self.expected_pass = expected_pass
        self.server: asyncio.AbstractServer | None = None
        self.port: int = 0
        self.writers: list[asyncio.StreamWriter] = []
        self.received: list[dict[str, Any]] = []
        self.pings_received: int = 0
        self.connect_auth_seen: list[tuple[str | None, str | None]] = []
        self.drop_next_pubacks: int = 0
        self.reject_all_pubacks: bool = False

    async def start(self, port: int = 0) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", port)
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        for w in list(self.writers):
            try:
                w.close()
                await w.wait_closed()
            except Exception:
                pass
        self.writers.clear()
        if self.server is not None:
            self.server.close()
            try:
                await asyncio.wait_for(self.server.wait_closed(), timeout=2.0)
            except Exception:
                pass
            self.server = None

    async def _read_rem_len(self, reader: asyncio.StreamReader) -> int:
        mult = 1
        val = 0
        for _ in range(4):
            b = (await reader.readexactly(1))[0]
            val += (b & 0x7F) * mult
            if (b & 0x80) == 0:
                return val
            mult *= 128
        raise ValueError("Invalid MQTT remaining length")

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writers.append(writer)
        try:
            while True:
                hdr = await reader.readexactly(1)
                ptype = hdr[0] & 0xF0
                flags = hdr[0] & 0x0F
                rem = await self._read_rem_len(reader)
                body = await reader.readexactly(rem) if rem else b""

                if ptype == 0x10:  # CONNECT
                    p_len = struct.unpack(">H", body[0:2])[0]
                    off = 2 + p_len + 1
                    cflags = body[off]
                    off += 1 + 2
                    cid_len = struct.unpack(">H", body[off:off + 2])[0]
                    off += 2 + cid_len
                    uname = pwd = None
                    if cflags & 0x80:
                        u_len = struct.unpack(">H", body[off:off + 2])[0]
                        off += 2
                        uname = body[off:off + u_len].decode("utf-8", errors="ignore")
                        off += u_len
                    if cflags & 0x40:
                        pw_len = struct.unpack(">H", body[off:off + 2])[0]
                        off += 2
                        pwd = body[off:off + pw_len].decode("utf-8", errors="ignore")
                        off += pw_len
                    self.connect_auth_seen.append((uname, pwd))
                    if self.expected_user is not None and (uname != self.expected_user or pwd != self.expected_pass):
                        writer.write(b"\x20\x02\x00\x05")  # Not authorized
                        await writer.drain()
                        break
                    writer.write(b"\x20\x02\x00\x00")  # CONNACK OK
                    await writer.drain()

                elif ptype == 0x30:  # PUBLISH
                    qos = (flags >> 1) & 0x03
                    dup = bool(flags & 0x08)
                    t_len = struct.unpack(">H", body[0:2])[0]
                    topic = body[2:2 + t_len].decode("utf-8", errors="replace")
                    off = 2 + t_len
                    pid = None
                    if qos > 0:
                        pid = struct.unpack(">H", body[off:off + 2])[0]
                        off += 2
                    payload = body[off:]
                    self.received.append({"topic": topic, "qos": qos, "dup": dup, "pid": pid, "payload": payload})
                    if qos == 1 and pid is not None:
                        if self.reject_all_pubacks:
                            continue
                        if self.drop_next_pubacks > 0:
                            self.drop_next_pubacks -= 1
                            continue
                        writer.write(struct.pack("!BBH", 0x40, 2, pid))
                        await writer.drain()

                elif ptype == 0xC0:  # PINGREQ
                    self.pings_received += 1
                    writer.write(b"\xD0\x00")  # PINGRESP
                    await writer.drain()

                elif ptype == 0xE0:  # DISCONNECT
                    break
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            if writer in self.writers:
                self.writers.remove(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


def render_clean_dial(value: float, v_min: float = 0.0, v_max: float = 16.0,
                      theta_min: float = 135.0, theta_max: float = 45.0,
                      direction: str = "cw", size: int = 640) -> np.ndarray:
    img = np.full((size, size, 3), (30, 34, 38), dtype=np.uint8)
    cx, cy = size // 2, size // 2
    r = int(size * 0.40)
    cv2.circle(img, (cx, cy), r + 18, (88, 94, 102), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r, (244, 245, 242), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r, (55, 60, 65), 2, cv2.LINE_AA)

    span = (theta_max - theta_min) % 360.0 if direction == "cw" else (theta_min - theta_max) % 360.0
    if span == 0:
        span = 360.0
    frac = (value - v_min) / (v_max - v_min)
    ang_deg = (theta_min + frac * span) % 360.0 if direction == "cw" else (theta_min - frac * span) % 360.0

    for i in range(41):
        a = (theta_min + (i / 40.0) * span) % 360.0 if direction == "cw" else (theta_min - (i / 40.0) * span) % 360.0
        ar = math.radians(a)
        c, s = math.cos(ar), math.sin(ar)
        r0 = r - (26 if i % 5 == 0 else 16)
        cv2.line(img, (int(cx + c * r0), int(cy + s * r0)), (int(cx + c * (r - 8)), int(cy + s * (r - 8))),
                 (30, 32, 35), 2 if i % 5 == 0 else 1, cv2.LINE_AA)

    ar = math.radians(ang_deg)
    c, s = math.cos(ar), math.sin(ar)
    nc, ns = -s, c
    tip = (cx + c * (r - 18), cy + s * (r - 18))
    tail = (cx - c * 32, cy - s * 32)
    pts = np.array([
        [tip[0], tip[1]],
        [cx + nc * 5, cy + ns * 5],
        [tail[0] + nc * 6, tail[1] + ns * 6],
        [tail[0] - nc * 6, tail[1] - ns * 6],
        [cx - nc * 5, cy - ns * 5],
    ], dtype=np.int32)
    cv2.fillConvexPoly(img, pts, (18, 20, 24), cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 12, (25, 28, 32), -1, cv2.LINE_AA)
    return img


# ---------------------------------------------------------------------------
# 1. DEF-01, DEF-06, DEF-19, DEF-21: MQTT QoS 1 + PUBACK + Auth + PING + S&F + Idempotency
# ---------------------------------------------------------------------------
def test_mqtt_qos1_sf_and_idempotency() -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        orig = (
            config.MQTT_ENABLED, config.MQTT_HOST, config.MQTT_PORT, config.MQTT_QOS,
            config.MQTT_USERNAME, config.MQTT_PASSWORD, config.MQTT_ACK_TIMEOUT,
            config.MQTT_MAX_RETRIES, config.SF_MAX_QUEUE_ROWS, config.SF_BATCH_DELAY_S,
        )
        broker = MockMqttQoS1Broker(expected_user="scada_u", expected_pass="scada_p")
        port = await broker.start()
        try:
            config.MQTT_ENABLED = True
            config.MQTT_HOST = "127.0.0.1"
            config.MQTT_PORT = port
            config.MQTT_QOS = 1
            config.MQTT_ACK_TIMEOUT = 0.35
            config.MQTT_MAX_RETRIES = 2
            config.SF_BATCH_DELAY_S = 0.0

            # 1a. Неверные credentials -> publish возвращает False
            config.MQTT_USERNAME = "wrong"
            config.MQTT_PASSWORD = "bad"
            bad_mqtt = MqttAsyncAdapter()
            ok_bad = await bad_mqtt.publish("gv/test", {"v": 1.0})
            assert ok_bad is False, "MQTT с неверными учётными данными должен возвращать False"
            await bad_mqtt.close()

            # 1b. Верные credentials + QoS 1 PUBACK + drop first PUBACK (DUP=1 retry) + PINGREQ
            config.MQTT_USERNAME = "scada_u"
            config.MQTT_PASSWORD = "scada_p"
            mqtt = MqttAsyncAdapter()
            assert await mqtt.publish("t1", {"event_uuid": "u1", "v": 13.5}) is True
            assert await mqtt.ping() is True
            assert broker.pings_received >= 1

            broker.drop_next_pubacks = 1
            assert await mqtt.publish("t2", {"event_uuid": "u2", "v": 14.1}) is True
            dups = [m for m in broker.received if m["topic"].endswith("/t2")]
            assert len(dups) == 2 and dups[1]["dup"] is True, f"Ожидался DUP=1 ретрай при потере PUBACK: {dups}"

            # 1c. S&F WAL + мёртвый брокер (DEF-01) + реальная доставка frame_blob (DEF-06) + идемпотентность (DEF-21)
            config.SF_MAX_QUEUE_ROWS = 30
            sf_path = _TMP / "sf_qos1_test.db"
            sf = StoreAndForwardBuffer(db_path=sf_path)
            await sf.init()
            st0 = await sf.stats()
            assert st0["wal_mode"] is True and st0["journal_mode"] == "wal"

            gw = ScadaGateway()
            gw.mqtt = mqtt
            sf.configure(deliver_cb=gw.deliver_batch)

            frame_bytes = b"\xff\xd8\xff\xe0" + b"FRAME_PAYLOAD_TEST_123456" * 30 + b"\xff\xd9"
            expected_sha = hashlib.sha256(frame_bytes).hexdigest()

            # Выключаем брокер -> жёсткий отказ доставки (DEF-01!)
            await broker.stop()
            res_down = await sf.enqueue(channel_id="ch-1", payload_type="telemetry", payload={"value": 12.1})
            assert res_down["status"] == "pending", f"При мёртвом брокере статус должен быть pending: {res_down}"
            res_alarm = await sf.enqueue(
                channel_id="ch-1", payload_type="alarm", payload={"value": 15.8},
                severity="alert", frame_blob=frame_bytes,
            )
            assert res_alarm["status"] == "pending" and res_alarm["size_bytes"] >= len(frame_bytes)

            flush_while_down = await sf.flush_pending(max_batches=3)
            assert flush_while_down["flushed"] == 0, f"При мёртвом брокере записи НЕ должны подтверждаться: {flush_while_down}"
            assert await sf.pending_count() == 2

            # Поднимаем брокер на том же порту -> досылка без потерь + frame_blob
            await broker.start(port=port)
            flush_up = await sf.flush_pending(max_batches=5)
            assert flush_up["flushed"] == 2 and await sf.pending_count() == 0, f"Ошибка досылки: {flush_up}"

            frame_msgs = [m for m in broker.received if m["topic"].endswith("/frame")]
            assert len(frame_msgs) >= 1, "Кадр frame_blob не был передан в SCADA"
            f_payload = json.loads(frame_msgs[-1]["payload"].decode("utf-8"))
            assert f_payload["frame_sha256"] == expected_sha and f_payload["frame_bytes"] == len(frame_bytes)
            assert gw.frames_delivered >= 1

            # Идемпотентная дедупликация по event_uuid (DEF-21)
            assert gw.receiver_ledger.accept("ev-dup-test") is True
            assert gw.receiver_ledger.accept("ev-dup-test") is False
            assert gw.status()["idempotency"]["duplicates_ignored"] >= 1

            # 1d. Политика переполнения квоты S&F (DEF-19): 5 alarm + 50 telemetry при лимите 30 строк
            await sf.set_outage(True, "quota_test")
            for i in range(5):
                await sf.enqueue(channel_id="ch-1", payload_type="alarm", payload={"seq": i}, severity="alert")
            for i in range(50):
                await sf.enqueue(channel_id="ch-1", payload_type="telemetry", payload={"seq": i}, severity="info")
            st_ov = await sf.stats()
            assert st_ov["pending_count"] <= 30, f"Лимит очереди нарушен: {st_ov}"
            assert st_ov["queue_overflow"] is True and st_ov["evicted_total"] >= 25
            con = sqlite3.connect(str(sf_path))
            alarms_left = con.execute("SELECT COUNT(*) FROM sf_queue WHERE status = 'pending' AND payload_type = 'alarm'").fetchone()[0]
            ov_logs = con.execute("SELECT COUNT(*) FROM sf_overflow_log").fetchone()[0]
            con.close()
            assert alarms_left == 5, f"Аварийные события не должны вытесняться при переполнении: {alarms_left}"
            assert ov_logs >= 1

            # 1e. Скорость досылки 250 записей (без sleep(0.15))
            config.SF_MAX_QUEUE_ROWS = 500
            sf2 = StoreAndForwardBuffer(db_path=_TMP / "sf_speed.db")
            await sf2.init()

            async def _fast_sink(batch: list[dict[str, Any]]) -> bool:
                return True

            sf2.configure(deliver_cb=_fast_sink)
            await sf2.set_outage(True, "speed")
            for i in range(250):
                await sf2.enqueue(channel_id=f"ch-{i % 4}", payload_type="telemetry", payload={"seq": i})
            sf2._outage_active = False
            t_drain0 = time.perf_counter()
            res_spd = await sf2.flush_pending(max_batches=20)
            drain_s = time.perf_counter() - t_drain0
            assert res_spd["flushed"] == 250 and drain_s < 1.5, f"Слишком медленный drain: {drain_s:.2f}s"

            await sf.close()
            await sf2.close()
            await mqtt.close()
            return {
                "puback_dup_retried": True,
                "pings_received": broker.pings_received,
                "frame_sha256_verified": True,
                "duplicates_ignored": gw.status()["idempotency"]["duplicates_ignored"],
                "alarms_preserved_on_overflow": alarms_left,
                "evicted_telemetry": st_ov["evicted_total"],
                "drain_250_seconds": round(drain_s, 3),
            }
        finally:
            await broker.stop()
            (
                config.MQTT_ENABLED, config.MQTT_HOST, config.MQTT_PORT, config.MQTT_QOS,
                config.MQTT_USERNAME, config.MQTT_PASSWORD, config.MQTT_ACK_TIMEOUT,
                config.MQTT_MAX_RETRIES, config.SF_MAX_QUEUE_ROWS, config.SF_BATCH_DELAY_S,
            ) = orig

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# 2. DEF-13: Modbus TCP unit_id validation + IEEE-754 quiet NaN for stale/invalid
# ---------------------------------------------------------------------------
def test_modbus_tcp_strict() -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        orig_en, orig_host, orig_port, orig_unit = (
            config.MODBUS_ENABLED, config.MODBUS_HOST, config.MODBUS_PORT, config.MODBUS_UNIT_ID
        )
        config.MODBUS_ENABLED = True
        config.MODBUS_HOST = "127.0.0.1"
        config.MODBUS_PORT = 15533
        config.MODBUS_UNIT_ID = 1
        mb = ModbusTcpGateway()
        mb.update_from_instruments([
            {"id": "c1", "code": "K1", "status": "online", "reading": {"valid": True, "value": 13.75, "level": "normal"}},
            {"id": "c2", "code": "K2", "status": "offline", "reading": {"valid": False, "value": None, "level": "normal"}},
        ], sf_pending=3, outage_active=False)
        await mb.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 15533)
            try:
                # 2a. Неверный unit_id=99 -> исключение 0x0B
                writer.write(struct.pack(">HHHBBHH", 1, 0, 6, 99, 3, 0, 4))
                await writer.drain()
                mbap = await asyncio.wait_for(reader.readexactly(7), timeout=2.0)
                _, _, ln, u = struct.unpack(">HHHB", mbap)
                pdu = await asyncio.wait_for(reader.readexactly(ln - 1), timeout=2.0)
                assert u == 99 and pdu[0] == 0x83 and pdu[1] == 0x0B, f"Ожидался Modbus 0x0B, получено {pdu.hex()}"

                # 2b. Канал 1 (addr 0..3, valid=13.75) и канал 2 (addr 4..7, stale -> quiet NaN 0x7FC00000)
                writer.write(struct.pack(">HHHBBHH", 2, 0, 6, 1, 3, 0, 8))
                await writer.drain()
                mbap = await asyncio.wait_for(reader.readexactly(7), timeout=2.0)
                _, _, ln, _ = struct.unpack(">HHHB", mbap)
                pdu = await asyncio.wait_for(reader.readexactly(ln - 1), timeout=2.0)
                assert pdu[0] == 3 and pdu[1] == 16
                regs = struct.unpack(">8H", pdu[2:18])
                val1 = struct.unpack(">f", struct.pack(">HH", regs[0], regs[1]))[0]
                assert abs(val1 - 13.75) < 1e-4, f"Канал 1 неверное значение: {val1}"
                val2_words = (regs[4], regs[5])
                val2 = struct.unpack(">f", struct.pack(">HH", *val2_words))[0]
                assert math.isnan(val2) and val2_words == (0x7FC0, 0x0000), f"Stale канал должен отдавать NaN 0x7FC00000, получено {val2_words}"
                assert regs[6] == 3  # status = STALE
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await mb.stop()
            config.MODBUS_ENABLED, config.MODBUS_HOST, config.MODBUS_PORT, config.MODBUS_UNIT_ID = (
                orig_en, orig_host, orig_port, orig_unit
            )
        return {"unit_id_99_exc": "0x0B", "valid_float32": 13.75, "stale_words": "0x7FC00000"}

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# 3. DEF-02, DEF-15: draw_overlay level consistency + CV partial occlusion rejection
# ---------------------------------------------------------------------------
def test_cv_overlay_and_occlusion() -> dict[str, Any]:
    cal = {"v_min": 0.0, "theta_min": 135.0, "v_max": 16.0, "theta_max": 45.0, "direction": "cw"}
    thr = {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True}

    clean = render_clean_dial(13.0)
    pipe_clean = vision.GaugePipeline("cv-clean")
    r_clean = pipe_clean.process(clean, cal, thr, "МПа", with_overlay=True)
    assert r_clean.valid is True and r_clean.value is not None and abs(r_clean.value - 13.0) < 0.3, f"Чистый кадр: {r_clean}"
    assert r_clean.status_level == "normal"

    # 44% частичное перекрытие -> отказ (DEF-15)
    occ = clean.copy()
    occ[:, :int(occ.shape[1] * 0.44)] = (15, 17, 19)
    pipe_occ = vision.GaugePipeline("cv-occ")
    r_occ = pipe_occ.process(occ, cal, thr, "МПа", with_overlay=True)
    assert r_occ.valid is False and r_occ.value is None, f"44% перекрытие должно отклоняться: {r_occ}"

    # draw_overlay при level='normal' НЕ рисует красный бейдж CRITICAL (DEF-02)
    alert_img = render_clean_dial(15.6)
    pipe_alert = vision.GaugePipeline("cv-alert")
    r_alert = pipe_alert.process(alert_img, cal, thr, "МПа", with_overlay=True)
    assert r_alert.valid is True and r_alert.status_level == "alert"

    ov_norm = r_clean.overlay
    ov_alert = r_alert.overlay
    assert ov_norm is not None and ov_alert is not None
    # Правая верхняя / левая верхняя область шапки (y < 60) — на normal не должно быть красного CRITICAL (#3B32E5 BGR)
    norm_red = int(np.sum((ov_norm[:60, :, 2] > 210) & (ov_norm[:60, :, 1] < 80) & (ov_norm[:60, :, 0] < 80)))
    alert_red = int(np.sum((ov_alert[:60, :, 2] > 210) & (ov_alert[:60, :, 1] < 80) & (ov_alert[:60, :, 0] < 80)))
    assert norm_red == 0, f"На NORMAL-кадре обнаружены красные пиксели CRITICAL: {norm_red}"
    assert alert_red > 100, f"На ALERT-кадре должен рисоваться красный бейдж: {alert_red}"

    assert r_occ.overlay is not None and r_occ.overlay.shape == occ.shape

    # render_gauge_frame с is_synthetic=True (DEF-04)
    synth = render_gauge_frame(
        code="К1-Р01", name="Манометр", unit="МПа", value=13.0,
        v_min=0.0, v_max=16.0, thresholds=thr, level="normal",
        annotate_cv=True, confidence=None, is_synthetic=True,
    )
    assert synth.shape[0] > 0

    return {
        "clean_val": round(r_clean.value, 3),
        "occ_44pct_valid": r_occ.valid,
        "occ_reason": r_occ.debug.get("invalid_reason"),
        "norm_red_px": norm_red,
        "alert_red_px": alert_red,
    }


# ---------------------------------------------------------------------------
# 4. DEF-10, DEF-11, DEF-12: RingBuffer concurrency+disk, FrameQuality real CV, Adaptive FPS wakeup
# ---------------------------------------------------------------------------
def test_streams_ring_quality_adaptive() -> dict[str, Any]:
    inc_dir = _TMP / "rb_test"
    rb = IncidentRingBuffer(pre_len=6, post_len=4, max_archives=10, storage_dir=inc_dir)
    dummy_jpg = cv2.imencode(".jpg", render_clean_dial(13.0, size=240))[1].tobytes()
    for _ in range(6):
        rb.push(dummy_jpg)
    c1 = rb.trigger("inc1", "alert", 15.5)["clip_id"]
    rb.push(dummy_jpg)
    c2 = rb.trigger("inc2", "alert", 15.9)["clip_id"]
    assert c1 != c2
    for _ in range(6):
        rb.push(dummy_jpg)
    st1 = rb.stats()
    assert st1["archived_clips"] == 2 and st1["persisted_clips"] == 2, f"Оба параллельных инцидента должны сохраниться: {st1}"

    rb2 = IncidentRingBuffer(pre_len=6, post_len=4, max_archives=10, storage_dir=inc_dir)
    st2 = rb2.stats()
    assert st2["archived_clips"] == 2 and st2["persisted_clips"] == 2, f"Клипы не восстановились с диска: {st2}"

    # FrameQualityAnalyzer: без читов injected_fault, partial occlusion, real drop counter (DEF-11)
    fqa = FrameQualityAnalyzer()
    base = render_clean_dial(12.0, size=320)
    q_ok = fqa.analyze(base)
    assert q_ok.health_status == "ONLINE" and q_ok.packet_loss_pct is None and q_ok.packet_loss_available is False, f"Ожидался ONLINE: {q_ok}"

    half_dark = base.copy()
    half_dark[:, :160] = 8
    q_occ = fqa.analyze(half_dark)
    assert q_occ.partial_occlusion is True and q_occ.health_status == "DEGRADED", f"Ожидался DEGRADED на 50% перекрытии: {q_occ}"

    for _ in range(5):
        fqa.record_drop()
    q_drop = fqa.analyze(base)
    assert q_drop.frame_drop_pct > 0.0 and q_drop.packet_loss_pct is None

    # AdaptiveFpsController: быстрое пробуждение по движению (DEF-12)
    afc = AdaptiveFpsController(idle_fps=1.0, active_fps=8.0, motion_mad_threshold=2.0)
    f1 = render_clean_dial(10.0, size=320)
    f2 = render_clean_dial(10.0, size=320)
    f3 = render_clean_dial(15.5, size=320)
    assert afc.check_motion_wakeup(f1) is False
    assert afc.check_motion_wakeup(f2) is False
    assert afc.check_motion_wakeup(f3) is True, "Сдвиг стрелки должен мгновенно будить eco_idle"
    info = afc.info()
    assert info["mode"] == "event_burst" and info["motion_wakeups_total"] >= 1

    return {
        "concurrent_clips_persisted": st2["persisted_clips"],
        "partial_occlusion_detected": True,
        "frame_drop_pct": round(q_drop.frame_drop_pct, 2),
        "motion_wakeup_triggered": True,
    }


# ---------------------------------------------------------------------------
# 5. DEF-08, DEF-14: DispatchAnalyzer — реальные dV/dt, 12h/24h окна, разделение health
# ---------------------------------------------------------------------------
def test_dispatch_analyzer_real_math() -> dict[str, Any]:
    an = DispatchAnalyzer()
    now = time.time()
    # Подаём линейную рампу 1 Гц (0.1 МПа/с = 6.0 МПа/мин) + дубликат timestamp
    for i in range(21):
        an._series.setdefault("t-ramp", __import__("collections").deque(maxlen=120)).append(
            (now - (20 - i), 10.0 + i * 0.1, "normal")
        )
    an._series["t-ramp"].append((now, 12.0, "normal"))  # дубликат timestamp

    # Плоский ряд для sim-12 (проверка, что _BENCH_DIAGNOSTIC_PROFILES удалён!)
    for i in range(20):
        an._series.setdefault("sim-12", __import__("collections").deque(maxlen=120)).append(
            (now - (60 - i * 3), 55.0, "normal")
        )

    inst_ramp = {
        "id": "t-ramp", "code": "T1", "name": "Тест рампа", "short_name": "Тест рампа",
        "group": "Котлы", "unit": "МПа", "gauge_type": "pressure", "decimals": 2, "source_kind": "live",
        "calibration": {"v_min": 0.0, "v_max": 16.0},
        "thresholds": {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.0, "hh_alert": 15.0, "lower_enabled": True},
        "reading": {"valid": True, "value": 12.0, "level": "normal"},
    }
    inst_fog = {
        "id": "sim-12", "code": "ТА2-Т02", "name": "Турбина тест", "short_name": "Турбина тест",
        "group": "Турбоагрегаты", "unit": "°C", "gauge_type": "temperature", "decimals": 1, "source_kind": "simulated",
        "calibration": {"v_min": 0.0, "v_max": 120.0},
        "thresholds": {"ll_alert": 20.0, "l_warn": 30.0, "h_warn": 80.0, "hh_alert": 95.0, "lower_enabled": True},
        "reading": {"valid": True, "value": 55.0, "level": "normal"},
    }

    now_dt = _dt.datetime.fromtimestamp(now, tz=_dt.timezone.utc)
    events = [
        {"id": 1, "cam_id": "t-ramp", "kind": "alarm", "level": "alert", "ts": (now_dt - _dt.timedelta(hours=1)).isoformat()},
        {"id": 2, "cam_id": "t-ramp", "kind": "alarm", "level": "alert", "ts": (now_dt - _dt.timedelta(hours=16)).isoformat()},
    ]
    streams = {
        "sim-12": {
            "health_status": "DEGRADED",
            "quality": {"steam_occlusion": True, "blur_score": 15.0, "frame_drop_pct": 0.0},
        }
    }
    r = an.analyze_instrument(inst_ramp, events, None, now_unix=now)
    f = an.analyze_instrument(inst_fog, events, streams["sim-12"], now_unix=now)

    assert abs(r["peak_rate_per_min"] - 6.0) < 0.05, f"Ожидалось 6.0 МПа/мин, получено {r['peak_rate_per_min']}"
    assert r["overload_min"] == 0.0, f"Не должно быть фантомных минут перегрузки: {r['overload_min']}"
    assert r["trips_shift"] == 1 and r["trips_24h"] == 2, f"Окна 12ч/24ч неверны: {r['trips_shift']}/{r['trips_24h']}"

    assert f["root_cause"] == "optical_degradation"
    assert f["equipment_health"] == 100.0 and f["instrument_health"] == 100.0
    assert f["optical_health"] < 50.0
    assert f["health_score"] == 100.0, f"Пар на камере не должен ронять технический health_score: {f['health_score']}"
    assert f["modernization_needed"] is False, "Чистая оптика не должна требовать замены КИП на цифровой датчик"
    assert f["chatter_pct"] < 0.1, f"Профиль _BENCH_DIAGNOSTIC_PROFILES не должен подделывать дребезг sim-12: {f['chatter_pct']}"

    return {
        "ramp_peak_rate_per_min": r["peak_rate_per_min"],
        "trips_12h_vs_24h": [r["trips_shift"], r["trips_24h"]],
        "fog_equipment_health": f["equipment_health"],
        "fog_optical_health": f["optical_health"],
        "fog_modernization_needed": f["modernization_needed"],
    }


# ---------------------------------------------------------------------------
# 6. DEF-03, DEF-17, DEF-22: SpecGenerator — реальные периоды БД, healthy=0 CAPEX, unknown=422, дисклеймер
# ---------------------------------------------------------------------------
def test_spec_generator_honesty() -> dict[str, Any]:
    an = DispatchAnalyzer()
    healthy_inst = {
        "id": "h1", "code": "К1-Н01", "name": "Здоровый манометр", "short_name": "Здоровый манометр",
        "group": "Котлы", "unit": "МПа", "gauge_type": "pressure", "decimals": 2, "source_kind": "live",
        "calibration": {"v_min": 0.0, "v_max": 16.0},
        "thresholds": {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.0, "hh_alert": 15.0, "lower_enabled": True},
        "reading": {"valid": True, "value": 12.0, "level": "normal"},
    }
    ov_h = an.overview([healthy_inst], events=[])

    async def _run_specs() -> dict[str, Any]:
        # 6a. Здоровый прибор -> 0 дефектов, 0 CAPEX, payback=None
        res_h = await generate_spec_bundle(
            dispatch_overview=ov_h, events=[], snapshot_lookup={},
            period="24h", group_filter="all", instrument_id="all",
        )
        assert len(res_h["defective_items"]) == 0 and len(res_h["tz_items"]) == 0
        assert res_h["economics"]["capex_rub"] == 0
        assert res_h["economics"]["payback_months"] is None and res_h["economics"]["payback_years"] is None
        assert "ФЗ-102" in res_h["markdown"] and LEGAL_DISCLAIMER[:40] in res_h["markdown"]

        # 6b. Только оптическая проблема (пар) -> 0 CAPEX на замену датчика
        ov_o = an.overview(
            [healthy_inst], events=[],
            stream_telemetry_map={"h1": {"health_status": "DEGRADED", "quality": {"steam_occlusion": True, "blur_score": 12.0}}},
        )
        res_o = await generate_spec_bundle(
            dispatch_overview=ov_o, events=[], snapshot_lookup={},
            period="24h", group_filter="all", instrument_id="all",
        )
        assert len(res_o["tz_items"]) == 0 and res_o["economics"]["capex_rub"] == 0
        assert len(res_o["defective_items"]) == 1 and res_o["defective_items"][0]["root_cause"] == "optical_degradation"

        # 6c. Неизвестная группа -> ValueError при strict_scope=True (DEF-17)
        got_err = False
        try:
            await generate_spec_bundle(
                dispatch_overview=ov_h, events=[], snapshot_lookup={},
                group_filter="Несуществующий цех", strict_scope=True,
            )
        except ValueError:
            got_err = True
        assert got_err is True, "Неизвестная группа должна вызывать ValueError при strict_scope=True"

        # 6d. Разные периоды 12h vs 24h vs 7d vs 30d на реальных данных SQLite (DEF-03)
        await db.init_db()
        cam_id = "period-test-p1"
        try:
            await db.create_camera(name="P1", type="rtsp", unit="МПа", cam_id=cam_id)
            now_dt = _dt.datetime.now(_dt.timezone.utc)
            iso = lambda delta: (now_dt - delta).isoformat(timespec="milliseconds")
            rows = [
                (cam_id, iso(_dt.timedelta(hours=2)), 12.0, 180.0, "normal", "МПа", None),
                (cam_id, iso(_dt.timedelta(hours=18)), 14.8, 220.0, "warning", "МПа", None),
                (cam_id, iso(_dt.timedelta(days=5)), 15.6, 240.0, "alert", "МПа", None),
                (cam_id, iso(_dt.timedelta(days=20)), 15.9, 248.0, "alert", "МПа", None),
            ]
            await db.insert_readings(rows)
            until = now_dt.isoformat(timespec="milliseconds")
            st_12 = await db.get_period_reading_stats(iso(_dt.timedelta(hours=12)), until, [cam_id])
            st_24 = await db.get_period_reading_stats(iso(_dt.timedelta(hours=24)), until, [cam_id])
            st_7d = await db.get_period_reading_stats(iso(_dt.timedelta(days=7)), until, [cam_id])
            st_30d = await db.get_period_reading_stats(iso(_dt.timedelta(days=30)), until, [cam_id])
            assert st_12[cam_id]["samples_count"] == 1 and st_12[cam_id]["max_val"] == 12.0
            assert st_24[cam_id]["samples_count"] == 2 and st_24[cam_id]["max_val"] == 14.8
            assert st_7d[cam_id]["samples_count"] == 3 and st_7d[cam_id]["max_val"] == 15.6
            assert st_30d[cam_id]["samples_count"] == 4 and st_30d[cam_id]["max_val"] == 15.9
            await db.delete_camera(cam_id)
        finally:
            await db.close_db()

        # 6e. Дисклеймер и структура в .docx (DEF-22)
        docx_bytes = render_spec_docx(res_h)
        with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as zf:
            txt = "".join(ET.fromstring(zf.read("word/document.xml")).itertext())
            assert "ФЗ-102" in txt and "ПАЗ" in txt

        return {
            "healthy_capex": 0,
            "optical_capex": 0,
            "unknown_group_rejected": True,
            "period_counts": {
                "12h": st_12[cam_id]["samples_count"],
                "24h": st_24[cam_id]["samples_count"],
                "7d": st_7d[cam_id]["samples_count"],
                "30d": st_30d[cam_id]["samples_count"],
            },
        }

    return asyncio.run(_run_specs())


# ---------------------------------------------------------------------------
# 7. DEF-07, DEF-09, DEF-20: RBAC, Path Traversal, SSRF, NaN 422, Encrypted RTSP Creds, Headers, Persistence
# ---------------------------------------------------------------------------
def test_security_rbac_and_persistence() -> dict[str, Any]:
    from app import main as app_main

    with TestClient(app_main.app) as client:
        # 7a. Заголовки безопасности на HTML/API
        r_idx = client.get("/")
        assert r_idx.status_code == 200
        assert r_idx.headers.get("x-frame-options") == "DENY"
        assert "content-security-policy" in {k.lower() for k in r_idx.headers.keys()}

        # 7b. Без аутентификации защищённые маршруты возвращают 401
        assert client.get("/api/cameras").status_code == 401
        assert client.post("/api/architecture/outage", json={"active": True}).status_code == 401
        assert client.post("/api/specs/preview", json={"period": "24h"}).status_code == 401

        ws_denied = False
        try:
            with client.websocket_connect("/ws/dashboard"):
                pass
        except Exception:
            ws_denied = True
        assert ws_denied is True, "Неавторизованный WebSocket /ws/dashboard должен отклоняться"

        # 7c. Оператор: чтение разрешено, изменение/управление — 403
        r_op = client.post("/api/auth/login", json={"username": "operator", "password": config.OPERATOR_PASSWORD})
        assert r_op.status_code == 200 and r_op.json()["role"] == "operator"
        assert client.get("/api/instruments").status_code == 200
        assert client.post("/api/cameras", json={"name": "X", "type": "rtsp", "source_url": "rtsp://10.0.0.5:554/s"}).status_code == 403
        assert client.post("/api/architecture/outage", json={"active": True}).status_code == 403
        assert client.get("/api/auth/users").status_code == 403

        # 7d. Инженер: управление ТЗ/камерами разрешено, users — 403
        r_eng = client.post("/api/auth/login", json={"username": "engineer", "password": config.ENGINEER_PASSWORD})
        assert r_eng.status_code == 200 and r_eng.json()["role"] == "engineer"
        assert client.get("/api/auth/users").status_code == 403

        # 7e. Админ: полный доступ
        r_adm = client.post("/api/auth/login", json={"username": "admin", "password": config.ADMIN_PASSWORD})
        assert r_adm.status_code == 200 and r_adm.json()["role"] == "admin"
        assert client.get("/api/auth/users").status_code == 200

        # 7f. Path traversal блокируется 422 (DEF-07)
        for bad_path in (r"C:\Windows\win.ini", "../../run.py", "/etc/passwd"):
            r_pt = client.post("/api/cameras", json={"name": "PT", "type": "video_file", "source_url": bad_path})
            assert r_pt.status_code == 422, f"Path traversal не заблокирован ({bad_path}): {r_pt.status_code} {r_pt.text}"

        # 7g. SSRF блокируется 422 (DEF-07)
        for bad_url in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8000/api/meta", "rtsp://8.8.8.8:554/stream"):
            ctype = "http_mjpeg" if bad_url.startswith("http") else "rtsp"
            r_ssrf = client.post("/api/cameras", json={"name": "SSRF", "type": ctype, "source_url": bad_url})
            assert r_ssrf.status_code == 422, f"SSRF не заблокирован ({bad_url}): {r_ssrf.status_code} {r_ssrf.text}"

        # 7h. Невалидная группа в /api/specs/preview -> 422 (DEF-17)
        r_bad_grp = client.post("/api/specs/preview", json={"period": "24h", "group": "НесуществующаяГруппа"})
        assert r_bad_grp.status_code == 422, f"Ожидался 422 для неизвестной группы: {r_bad_grp.status_code}"

        # 7i. NaN / Inf в JSON -> 422, НЕ 500 (DEF-09)
        r_nan = client.patch(
            "/api/cameras/demo-mtp160-steam",
            content='{"thresholds": {"h_warn": NaN, "hh_alert": 15.2}}',
            headers={"Content-Type": "application/json"},
        )
        assert r_nan.status_code == 422, f"NaN должен возвращать 422, получено {r_nan.status_code}"

        # 7j. Шифрование RTSP-пароля в SQLite и маскирование во всех API (DEF-07)
        secret_pw = "SuperSecretRtspPass99"
        r_rtsp = client.post("/api/cameras", json={
            "name": "Стенд RTSP",
            "type": "rtsp",
            "source_url": f"rtsp://admin:{secret_pw}@192.168.100.55:554/stream1",
        })
        assert r_rtsp.status_code == 201, f"Разрешённый RFC1918 RTSP должен создаваться: {r_rtsp.text}"
        cam_id = r_rtsp.json()["id"]
        assert secret_pw not in r_rtsp.text and "***" in r_rtsp.text

        for ep in ("/api/cameras", f"/api/cameras/{cam_id}", "/api/architecture/streams"):
            resp_txt = client.get(ep).text
            assert secret_pw not in resp_txt, f"Пароль RTSP утёк в {ep}!"

        con = sqlite3.connect(os.environ["GAUGEVISION_DB"])
        raw_db_url = con.execute("SELECT source_url FROM cameras WHERE id = ?", (cam_id,)).fetchone()[0]
        con.close()
        assert secret_pw not in raw_db_url and raw_db_url.startswith("enc:v1:"), f"Пароль не зашифрован в SQLite: {raw_db_url}"
        client.delete(f"/api/cameras/{cam_id}")

        # 7k. Автогенерация ТЗ по критическому порогу (/api/specs/auto) и журнал аудита (/api/auth/audit)
        r_auto = client.get("/api/specs/auto")
        assert r_auto.status_code == 200
        r_aud = client.get("/api/auth/audit")
        assert r_aud.status_code == 200 and len(r_aud.json()) >= 3

        # 7l. Проверка персистентности EventLog в SQLite
        con = sqlite3.connect(os.environ["GAUGEVISION_DB"])
        persisted_evs = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        con.close()
        assert persisted_evs >= 1, f"События должны сохраняться в SQLite: {persisted_evs}"

    return {
        "rbac_matrix_ok": True,
        "path_traversal_422": True,
        "ssrf_422": True,
        "nan_422": True,
        "rtsp_encrypted_at_rest": True,
        "rtsp_masked_in_api": True,
        "events_persisted_sqlite": persisted_evs,
    }


# ---------------------------------------------------------------------------
# 8. Проверка локального HTTP-MJPEG потока (подтверждение сетевого захвата OpenCV)
# ---------------------------------------------------------------------------
def test_local_http_mjpeg_capture() -> dict[str, Any]:
    jpeg_frame = cv2.imencode(".jpg", render_clean_dial(11.2, size=480))[1].tobytes()
    stop_flag = threading.Event()

    class MjpegHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            while not stop_flag.is_set():
                try:
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(jpeg_frame)).encode()
                        + b"\r\n\r\n"
                        + jpeg_frame
                        + b"\r\n"
                    )
                    self.wfile.flush()
                    time.sleep(0.04)
                except OSError:
                    break

    srv = ThreadingHTTPServer(("127.0.0.1", 0), MjpegHandler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        from app.streamer import CaptureWorker, FrameBroker

        broker = FrameBroker()
        loop = asyncio.new_event_loop()
        worker = CaptureWorker("mjpeg-test", "http_mjpeg", f"http://127.0.0.1:{port}/stream.mjpg", broker, loop, None)
        worker.start()
        deadline = time.time() + 10.0
        got_frame = None
        while time.time() < deadline:
            frm, _ = broker.latest_frame("mjpeg-test")
            if frm is not None:
                got_frame = frm
                break
            time.sleep(0.1)
        worker.stop()
        worker.join(timeout=2.0)
        loop.close()
        assert got_frame is not None, "Не удалось получить кадр из локального HTTP-MJPEG потока"
        cal = {"v_min": 0.0, "theta_min": 135.0, "v_max": 16.0, "theta_max": 45.0, "direction": "cw"}
        thr = {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True}
        res = vision.GaugePipeline("mjpeg-cv").process(got_frame, cal, thr, "МПа", with_overlay=False)
        assert res.valid is True and res.value is not None and abs(res.value - 11.2) < 0.35, f"Неверное чтение из MJPEG: {res}"
        return {"mjpeg_port": port, "frame_shape": list(got_frame.shape), "read_value": round(res.value, 3)}
    finally:
        stop_flag.set()
        srv.shutdown()
        srv.server_close()


def main() -> None:
    record_case("mqtt_qos1_sf_and_idempotency", ["DEF-01", "DEF-06", "DEF-19", "DEF-21"], test_mqtt_qos1_sf_and_idempotency)
    record_case("modbus_tcp_strict_and_nan", ["DEF-13"], test_modbus_tcp_strict)
    record_case("cv_overlay_and_partial_occlusion", ["DEF-02", "DEF-15"], test_cv_overlay_and_occlusion)
    record_case("streams_ring_quality_adaptive", ["DEF-10", "DEF-11", "DEF-12"], test_streams_ring_quality_adaptive)
    record_case("dispatch_analyzer_real_math", ["DEF-08", "DEF-14"], test_dispatch_analyzer_real_math)
    record_case("spec_generator_honesty_and_periods", ["DEF-03", "DEF-04", "DEF-17", "DEF-22"], test_spec_generator_honesty)
    record_case("security_rbac_and_persistence", ["DEF-07", "DEF-09", "DEF-20"], test_security_rbac_and_persistence)
    record_case("local_http_mjpeg_capture", ["REQ-T2-02"], test_local_http_mjpeg_capture)

    out_path = os.environ.get("REMEDIATION_TEST_OUT")
    summary = {
        "total": len(RESULTS),
        "passed": sum(1 for r in RESULTS if r["passed"]),
        "failed": sum(1 for r in RESULTS if not r["passed"]),
        "cases": RESULTS,
    }
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ALL REMEDIATION TESTS PASSED: {summary['passed']}/{summary['total']}")


if __name__ == "__main__":
    main()
