"""
Интеграционные испытания GaugeVision AI со сторонними реализациями протоколов.

Сценарий (строго CPU, всё локально, без внешней сети):
  1. RTSP: mediamtx (с аутентификацией) + ffmpeg публикуют видеофайл стрелочного прибора
     с известными показаниями 6,0 / 11,5 МПа; камера добавляется через REST с паролем в URL.
     Проверяются подключение, точность CV по эталону, маскирование пароля, обрыв и
     автоматическое восстановление потока (издатель и сервер RTSP).
  2. MQTT: сторонний брокер amqtt и подписчик amqtt. Брокер реально останавливается
     на время работы; Store-and-Forward накапливает данные и досылает их после запуска.
     Сверка «записано в sf_queue → получено подписчиком» по event_uuid, дубли, SHA-256 кадров.
  3. Смартфон-камера по WSS (/ws/phone) с переходом в аварию для тревоги с кадром.
  4. Modbus TCP: сторонний клиент pymodbus читает карту регистров, чужой unit_id,
     системный блок; сверка с REST.

Запуск:
  python reports/remediation/tests/interop_rtsp_mqtt_modbus.py --out reports/remediation/evidence/interop
Инструменты: setup_validation_tools.py (или переменные GV_TOOLS_PY, GV_AMQTT, GV_MEDIAMTX, GV_FFMPEG).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import shutil
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gv_harness as H  # noqa: E402

import cv2  # noqa: E402
import websockets  # noqa: E402


class PhoneClient(threading.Thread):
    """Эмулятор веб-клиента смартфона: шлёт JPEG-кадры прибора по WSS с заданным значением."""

    def __init__(self, base_wss: str, cam_id: str, token: str, fps: float = 3.0) -> None:
        super().__init__(daemon=True)
        self.url = f"{base_wss}/ws/phone/{cam_id}?token={token}"
        self.value = 13.0
        self.fps = fps
        self.sent = 0
        self.acks = 0
        self.errors: list[str] = []
        self._stop = threading.Event()

    def run(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, ssl=H.insecure_ssl(), max_size=None) as ws:
                    await ws.recv()  # hello
                    while not self._stop.is_set():
                        ok, buf = cv2.imencode(".jpg", H.gauge_frame(self.value, code="К1-Р01"),
                                               [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                        await ws.send(buf.tobytes())
                        self.sent += 1
                        msg = json.loads(await ws.recv())
                        if msg.get("type") == "ack":
                            self.acks += 1
                        await asyncio.sleep(1.0 / self.fps)
            except Exception as exc:  # переподключение, как у реального клиента
                self.errors.append(f"{type(exc).__name__}: {exc}"[:200])
                await asyncio.sleep(1.0)

    def stop(self) -> None:
        self._stop.set()


def wait_for(pred, timeout: float, step: float = 0.5) -> float | None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if pred():
                return round(time.time() - t0, 2)
        except Exception:
            pass
        time.sleep(step)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(H.ROOT / "reports" / "remediation" / "evidence" / "interop"))
    ap.add_argument("--tools", default=None)
    ap.add_argument("--skip-rtsp", action="store_true", help="без RTSP-стенда (mediamtx/ffmpeg)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tools = H.load_tools(args.tools)
    work = Path(tempfile.mkdtemp(prefix="gv_interop_"))
    res: dict[str, Any] = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "checks": {}}
    checks = res["checks"]

    use_rtsp = not args.skip_rtsp
    res["rtsp_enabled"] = use_rtsp
    rtsp = None
    if use_rtsp:
        video = H.make_gauge_video(work / "gauge_rtsp.mp4", [(8.0, 6.0), (8.0, 11.5)], fps=10)
        rtsp = H.RtspStand(tools, work / "rtsp", video)
    broker = H.AmqttBroker(tools, work / "mqtt")
    sub = H.MqttSubscriber(tools, broker.port, work / "mqtt" / "received.jsonl")
    mb_port = H.free_port()
    server = H.GaugeServer(work / "server", extra_env={
        "GAUGEVISION_MQTT_ENABLED": "1", "GAUGEVISION_MQTT_HOST": "127.0.0.1",
        "GAUGEVISION_MQTT_PORT": str(broker.port), "GAUGEVISION_MQTT_ACK_TIMEOUT": "2.0",
        "GAUGEVISION_MQTT_KEEPALIVE": "10", "GAUGEVISION_MODBUS_ENABLED": "1",
        "GAUGEVISION_MODBUS_HOST": "127.0.0.1", "GAUGEVISION_MODBUS_PORT": str(mb_port),
        "GAUGEVISION_ALLOW_LOOPBACK_STREAMS": "1",
    })
    phone: PhoneClient | None = None
    try:
        if rtsp:
            rtsp.start_server()
            rtsp.start_publisher()
        broker.start()
        sub.start()
        t0 = time.time()
        server.start()
        res["server_start_s"] = round(time.time() - t0, 1)
        api = H.Api(server.base, "engineer", H.ENGINEER_PASS)
        adm = H.Api(server.base, "admin", H.ADMIN_PASS)

        # ---------------- 1. RTSP ----------------
        if rtsp:
            r = api.post("/api/cameras", {"name": "RTSP-камера стенда", "type": "rtsp", "source_url": rtsp.view_url,
                                          "calibration": H.CALIBRATION, "thresholds": H.THRESHOLDS})
            assert r.status_code == 201, r.text
            cam = r.json()
            cid = cam["id"]
            checks["rtsp_url_masked_in_response"] = H.RtspStand.VIEW_PASS not in r.text and "***:***@" in cam["source_url"]

            def cam_state() -> dict[str, Any]:
                return api.get(f"/api/cameras/{cid}")

            t_online = wait_for(lambda: cam_state()["status"] == "online", 60)
            t_valid = wait_for(lambda: (cam_state().get("reading") or {}).get("valid") is True, 60)
            checks["rtsp_connect_s"] = t_online
            checks["rtsp_first_valid_reading_s"] = t_valid
            samples = []
            t_end = time.time() + 40
            while time.time() < t_end:
                st = cam_state()
                rd = st.get("reading") or {}
                if rd.get("valid") and rd.get("raw_value") is not None:
                    samples.append({"raw": rd["raw_value"], "ema": rd.get("value"), "ms": rd.get("process_ms"),
                                    "fps": (st.get("stream") or {}).get("fps")})
                time.sleep(0.5)
            errs = [min(abs(s["raw"] - 6.0), abs(s["raw"] - 11.5)) for s in samples]
            near = [e for e in errs if e <= 0.35]
            checks["rtsp_cv"] = {
                "samples": len(samples),
                "within_0_35_MPa_of_reference": len(near),
                "share_within": round(len(near) / max(1, len(samples)), 3),
                "mae_vs_nearest_reference": round(statistics.mean(errs), 4) if errs else None,
                "p50_process_ms": round(statistics.median([s["ms"] for s in samples if s["ms"]]), 1) if samples else None,
                "stream_fps_median": statistics.median([s["fps"] for s in samples if s["fps"] is not None]) if samples else None,
                "saw_6_0": any(abs(s["raw"] - 6.0) <= 0.35 for s in samples),
                "saw_11_5": any(abs(s["raw"] - 11.5) <= 0.35 for s in samples),
            }
            hist = api.get(f"/api/cameras/{cid}/history?limit=500")
            checks["rtsp_readings_in_sqlite"] = len(hist)

            # Обрыв издателя RTSP и автоматическое восстановление
            rtsp.stop_publisher()
            checks["rtsp_publisher_down_detected_s"] = wait_for(lambda: cam_state()["status"] != "online", 60)
            # Диагностика канала во время обрыва: реальные пропуски чтения кадров (REQ-VA-08)
            drop_samples = []
            for _ in range(8):
                q = next((s.get("quality") or {} for s in api.get("/api/architecture/streams") if s["id"] == cid), {})
                drop_samples.append({"frame_drop_pct": q.get("frame_drop_pct"), "health": q.get("health_status"),
                                     "reasons": q.get("degradation_reasons")})
                time.sleep(1.0)
            checks["rtsp_outage_channel_diagnostics"] = drop_samples
            rtsp.start_publisher()
            checks["rtsp_publisher_recovered_s"] = wait_for(lambda: cam_state()["status"] == "online", 90)
            # Полная остановка RTSP-сервера и его повторный запуск
            rtsp.stop()
            checks["rtsp_server_down_detected_s"] = wait_for(lambda: cam_state()["status"] != "online", 60)
            time.sleep(5)
            rtsp.start_server()
            rtsp.start_publisher()
            checks["rtsp_server_recovered_s"] = wait_for(lambda: cam_state()["status"] == "online", 120)
            # Инференс возобновился: новое достоверное показание с меткой времени после восстановления
            t_rec = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

            def fresh_valid() -> bool:
                rd = cam_state().get("reading") or {}
                return bool(rd.get("valid")) and str(rd.get("ts", "")) > t_rec and                     min(abs(rd["raw_value"] - 6.0), abs(rd["raw_value"] - 11.5)) <= 0.35
            checks["rtsp_inference_resumed_s"] = wait_for(fresh_valid, 60)
            st_final = cam_state()
            checks["rtsp_stream_after_recovery"] = {k: (st_final.get("stream") or {}).get(k) for k in ("status", "fps", "fail_count", "last_error")}

            # Изоляция: остальные каналы продолжали работать во время обрыва RTSP
            arch = api.get("/api/architecture/streams")
            checks["other_channels_online_during_test"] = sorted(
                (s["id"], s["status"]) for s in arch if s["id"] != cid and s.get("is_bench"))

        # ---------------- 2. Смартфон-камера по WSS ----------------
        sess = api.post("/api/phone/session", {}).json()
        phone = PhoneClient(server.base.replace("https://", "wss://"), sess["cam_id"], sess["token"])
        phone.start()
        checks["phone_first_valid_s"] = wait_for(
            lambda: (api.get(f"/api/cameras/{sess['cam_id']}").get("reading") or {}).get("valid") is True, 60)

        # ---------------- 3. MQTT через сторонний брокер ----------------
        checks["mqtt_connected_s"] = wait_for(lambda: api.get("/api/scada/status")["mqtt"]["connected"], 30)
        time.sleep(8)
        sc0 = api.get("/api/scada/status")["mqtt"]
        checks["mqtt_before_outage"] = {k: sc0[k] for k in ("mode", "broker_sent", "puback_received", "publish_failures")}
        n_before = len(sub.messages())

        broker.stop()
        t_down = time.time()
        phone.value = 15.7  # авария на живом приборе во время отказа брокера: тревога с кадром
        pend_series = []
        while time.time() - t_down < 45:
            sf = api.get("/api/architecture/store-forward")
            pend_series.append({"t": round(time.time() - t_down, 1), "pending": sf["pending_count"],
                                "pending_alarms": sf["pending_alarms"], "sync_state": sf["sync_state"]})
            time.sleep(3)
        phone.value = 13.0
        sc_down = api.get("/api/scada/status")["mqtt"]
        checks["mqtt_during_outage"] = {"pending_series": pend_series, "mode": sc_down["mode"],
                                        "publish_failures": sc_down["publish_failures"]}
        peak_pending = max(p["pending"] for p in pend_series)

        broker.start()
        t_up = time.time()
        drained = wait_for(lambda: api.get("/api/architecture/store-forward")["pending_count"] == 0, 180, step=1.0)
        checks["mqtt_recovery"] = {"peak_pending": peak_pending, "drain_s": drained,
                                   "reconnect_s": wait_for(lambda: api.get("/api/scada/status")["mqtt"]["connected"], 30)}
        time.sleep(4)

        # Сверка доставки: каждое событие очереди получено подписчиком
        sf_db = server.data_dir / "store_forward.db"
        con = sqlite3.connect(f"file:{sf_db}?mode=ro", uri=True)
        rows = con.execute("SELECT event_uuid, status, payload_type, frame_sha256, created_at FROM sf_queue").fetchall()
        con.close()
        msgs = sub.messages()
        got_uuids: dict[str, int] = {}
        for m in msgs:
            if m.get("event_uuid") and not m["topic"].endswith("/frame"):
                got_uuids[m["event_uuid"]] = got_uuids.get(m["event_uuid"], 0) + 1
        sent_rows = [r for r in rows if r[1] == "sent"]
        missing = [r[0] for r in sent_rows if r[0] not in got_uuids]
        frames = [m for m in msgs if m["topic"].endswith("/frame")]
        checks["mqtt_delivery_reconciliation"] = {
            "sf_rows_total": len(rows),
            "sf_rows_sent": len(sent_rows),
            "sf_rows_pending": sum(1 for r in rows if r[1] == "pending"),
            # свежие записи ещё в пути (очередь пополняется каждые 2 с); залежавшиеся — потеря
            "sf_rows_pending_older_10s": sum(
                1 for r in rows if r[1] == "pending"
                and time.time() - _dt.datetime.fromisoformat(r[4]).timestamp() > 10.0),
            "subscriber_messages": len(msgs),
            "subscriber_before_outage": n_before,
            "sent_but_not_received": len(missing),
            "duplicate_deliveries": sum(c - 1 for c in got_uuids.values() if c > 1),
            "alarm_rows": sum(1 for r in rows if r[2] == "alarm"),
            "alarm_rows_with_frame": sum(1 for r in rows if r[2] == "alarm" and r[3]),
            "frames_received": len(frames),
            "frames_sha256_ok": all(f.get("frame_sha256_actual") == f.get("frame_sha256_declared") for f in frames),
        }

        # ---------------- 4. Modbus TCP сторонним клиентом ----------------
        regs_api = api.get("/api/scada/modbus/registers")
        mb = H.modbus_probe(tools, mb_port, unit=1, start=0, count=120)
        api_rows = regs_api["instruments"]
        cmp_ok = 0
        cmp_n = 0
        nan_ok = True
        for row, dec in zip(api_rows, mb.get("instruments", [])):
            cmp_n += 1
            if row["value"] is None:
                nan_ok = nan_ok and dec["is_nan"]
                cmp_ok += 1 if dec["is_nan"] else 0
            elif dec["value"] is not None and abs(dec["value"] - row["value"]) <= max(0.05, abs(row["value"]) * 0.02):
                cmp_ok += 1
        sysblk = H.modbus_probe(tools, mb_port, unit=1, start=900, count=6)
        foreign = H.modbus_probe(tools, mb_port, unit=99, start=0, count=4)
        bad_addr = H.modbus_probe(tools, mb_port, unit=1, start=1020, count=10)
        checks["modbus_pymodbus"] = {
            "instruments_compared": cmp_n,
            "matched_api_values": cmp_ok,
            "stale_encoded_as_nan": nan_ok,
            "system_block": sysblk.get("registers"),
            "foreign_unit_99": {"error": foreign.get("error"), "exception_code": foreign.get("exception_code")},
            "out_of_range_address": {"error": bad_addr.get("error"), "exception_code": bad_addr.get("exception_code")},
        }

        # ---------------- 5. Утечки пароля RTSP ----------------
        bodies = [json.dumps(adm.get(p), ensure_ascii=False) for p in (
            "/api/cameras", "/api/architecture/streams", "/api/architecture/status", "/api/instruments")]
        time.sleep(1)
        log_txt = server.log_path.read_text(encoding="utf-8", errors="replace")
        if rtsp:
            checks["rtsp_password_leaks"] = {
                "api": sum(H.RtspStand.VIEW_PASS in b for b in bodies),
                "server_log": log_txt.count(H.RtspStand.VIEW_PASS),
            }
        api.close()
        adm.close()
    finally:
        if phone:
            phone.stop()
        rc = server.stop()
        res["server_exit_code"] = rc
        srv_log = server.log_path.read_text(encoding="utf-8", errors="replace") if server.log_path.is_file() else ""
        res["server_graceful_shutdown_logged"] = "Application shutdown complete" in srv_log
        res["token_leaks_in_server_log"] = sum(1 for ln in srv_log.splitlines() if "token=" in ln and "token=***" not in ln)
        sub.stop()
        broker.stop()
        if rtsp:
            rtsp.stop()
        for p in (server.log_path, work / "mqtt" / "received.jsonl", work / "mqtt" / "amqtt_broker.log",
                  work / "rtsp" / "mediamtx.log", work / "rtsp" / "ffmpeg_publisher.log"):
            if p.is_file():
                shutil.copy2(p, out / p.name)
    if phone:
        res["phone_client"] = {"sent": phone.sent, "acks": phone.acks, "errors": phone.errors[:5]}
    res["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    c = checks
    rec = c["mqtt_delivery_reconciliation"]
    verdict: dict[str, bool] = {}
    if use_rtsp:
        verdict.update({
            "rtsp_online": c["rtsp_connect_s"] is not None,
            "rtsp_cv_accuracy": c["rtsp_cv"]["share_within"] >= 0.9 and c["rtsp_cv"]["saw_6_0"] and c["rtsp_cv"]["saw_11_5"],
            "rtsp_auto_recovery": c["rtsp_publisher_recovered_s"] is not None and c["rtsp_server_recovered_s"] is not None,
            "rtsp_inference_resumed": c.get("rtsp_inference_resumed_s") is not None,
            "rtsp_outage_degradation_reported": any((d.get("frame_drop_pct") or 0) > 0 or d.get("health") in ("DEGRADED", "OFFLINE")
                                                    for d in c.get("rtsp_outage_channel_diagnostics", [])),
            "rtsp_password_masked": c["rtsp_url_masked_in_response"] and c["rtsp_password_leaks"] == {"api": 0, "server_log": 0},
        })
    verdict.update({
        "no_tokens_in_server_log": res.get("token_leaks_in_server_log", 1) == 0,
        "mqtt_buffered_during_outage": c["mqtt_recovery"]["peak_pending"] > 0,
        "mqtt_drained_after_recovery": c["mqtt_recovery"]["drain_s"] is not None,
        "mqtt_no_loss": rec["sent_but_not_received"] == 0 and rec["sf_rows_pending_older_10s"] == 0,
        "mqtt_frames_intact": rec["frames_received"] > 0 and rec["frames_sha256_ok"],
        "modbus_values_match": c["modbus_pymodbus"]["matched_api_values"] >= int(0.9 * max(1, c["modbus_pymodbus"]["instruments_compared"])),
        "modbus_foreign_unit_rejected": c["modbus_pymodbus"]["foreign_unit_99"]["error"] is True,
        # Windows: после штатного завершения uvicorn повторно поднимает SIGBREAK (код 3) —
        # критерий штатности — завершение lifespan в журнале сервера
        "server_graceful_exit": res.get("server_graceful_shutdown_logged", False),
    })
    res["verdict"] = verdict
    res["passed"] = all(verdict.values())
    (out / "interop_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    print("INTEROP PASSED" if res["passed"] else "INTEROP FAILED")
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
