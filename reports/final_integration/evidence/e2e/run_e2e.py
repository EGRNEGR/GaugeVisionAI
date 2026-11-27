"""
Сквозное испытание объединённого GaugeVision AI 3.0 (19 шагов, FINAL_ACCEPTANCE § 8).

Стенд: отдельный процесс сервера `run.py` (HTTPS), сторонний MQTT-брокер amqtt, Modbus TCP
127.0.0.1:15020 (его опрашивает лабораторная Ignition 8.3.10), Tag Historian Ignition читается
только на чтение как независимая запись того, что SCADA получила по Modbus.

Источник — синтетический видеофайл щита (scripts/make_panel_video.py: 8 приборов, значения постоянны,
прибор 1 дрейфует). Это не видео действующего объекта; так он и подписан во всех результатах.

    python run_e2e.py --video <panel.mp4> --work <каталог> --amqtt <amqtt.exe> --tools-py <python инструментов>
                      [--historian <samplequickstart.db>] [--out e2e_results.json]
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT = Path(__file__).resolve().parents[4]
STEPS: list[dict[str, Any]] = []
PW = {"admin": "E2e-Admin-7351", "engineer": "E2e-Eng-7351", "operator": "E2e-Op-7351"}


def step(n: int, title: str, ok: bool, **details: Any) -> None:
    STEPS.append({"step": n, "title": title, "passed": bool(ok), "details": details, "t": time.time()})
    print(f"[{'PASS' if ok else 'FAIL'}] {n:02d}. {title} {json.dumps(details, ensure_ascii=False, default=str)[:300]}",
          flush=True)


def wait_for(pred: Callable[[], Any], timeout: float, poll: float = 0.5) -> Any:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = pred()
        except Exception:  # noqa: BLE001
            v = None
        if v:
            return v
        time.sleep(poll)
    return None


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def modbus_read(addr: int, count: int, port: int = 15020) -> list[int]:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
        s.sendall(struct.pack(">HHHBBHH", 7, 0, 6, 1, 3, addr, count))
        hdr = s.recv(9)
        n = hdr[8]
        data = b""
        while len(data) < n:
            data += s.recv(n - len(data))
    return list(struct.unpack(f">{count}H", data))


def f32(hi: int, lo: int) -> float:
    return struct.unpack(">f", struct.pack(">HH", hi, lo))[0]


class Server:
    def __init__(self, work: Path, env: dict[str, str], port: int) -> None:
        self.work, self.env, self.port = work, env, port
        self.proc: subprocess.Popen | None = None
        self.log = work / "server.log"

    def start(self) -> float:
        t0 = time.time()
        logf = open(self.log, "a", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-B", "run.py", "--no-demo", "--host", "127.0.0.1", "--port", str(self.port),
             "--device", "cpu", "--log-level", "warning"],
            cwd=str(ROOT), env=self.env, stdout=logf, stderr=subprocess.STDOUT)
        ok = wait_for(lambda: httpx.get(f"https://127.0.0.1:{self.port}/api/health", verify=False, timeout=2)
                      .status_code == 200, 90)
        if not ok:
            raise RuntimeError("сервер не поднялся, см. server.log")
        return time.time() - t0

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


class Broker:
    def __init__(self, exe: str, work: Path, port: int) -> None:
        self.exe, self.port = exe, port
        self.cfg = work / "amqtt.yaml"
        self.cfg.write_text("listeners:\n  default:\n    type: tcp\n    bind: 127.0.0.1:%d\n"
                            "plugins:\n  amqtt.plugins.authentication.AnonymousAuthPlugin:\n"
                            "    allow_anonymous: true\n" % port, encoding="utf-8")
        self.log = work / "amqtt.log"
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.proc = subprocess.Popen([self.exe, "-c", str(self.cfg)], stdout=open(self.log, "a"),
                                     stderr=subprocess.STDOUT)
        if not wait_for(lambda: socket.create_connection(("127.0.0.1", self.port), 0.5).close() or True, 20):
            raise RuntimeError("amqtt не открыл порт")

    def stop(self) -> None:
        if self.proc:
            self.proc.kill()
            self.proc.wait(10)
            self.proc = None


class Historian:
    """Tag Historian Ignition (SQLite quick start), только чтение."""

    def __init__(self, path: str | None) -> None:
        self.path = path

    def _con(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)

    def series(self, tagpath: str, since_ms: int) -> list[tuple[int, float | None, int]]:
        if not self.path:
            return []
        con = self._con()
        try:
            ids = [r[0] for r in con.execute("SELECT id FROM sqlth_te WHERE lower(tagpath) = ?", (tagpath.lower(),))]
            if not ids:
                return []
            tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'sqlt_data_%'")]
            out: list[tuple[int, float | None, int]] = []
            for t in tabs:
                q = (f"SELECT t_stamp, COALESCE(floatvalue, intvalue), dataintegrity FROM {t} "
                     f"WHERE tagid IN ({','.join('?' * len(ids))}) AND t_stamp >= ? ORDER BY t_stamp")
                out += [(int(a), b, int(c)) for a, b, c in con.execute(q, (*ids, since_ms))]
            return sorted(out)
        finally:
            con.close()


def tag_folder(slot: int) -> str | None:
    """Папка прибора в дереве тегов Ignition по номеру слота (экспорт integrations/ignition/tags)."""
    tags = json.loads((ROOT / "integrations/ignition/tags/gaugevision_tags.json").read_text(encoding="utf-8"))

    def walk(node: dict[str, Any]) -> list[dict[str, Any]]:
        res = [node]
        for ch in node.get("tags") or []:
            res += walk(ch)
        return res
    for n in walk(tags):
        if n.get("tagType") == "Folder" and str(n.get("name", "")).upper().startswith(f"P{slot + 1:02d}_"):
            return n["name"]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--amqtt", required=True)
    ap.add_argument("--tools-py", required=True)
    ap.add_argument("--historian", default=None)
    ap.add_argument("--out", default=str(Path(__file__).with_name("e2e_results.json")))
    ap.add_argument("--predict-timeout", type=float, default=600.0)
    args = ap.parse_args()

    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    (work / "videos").mkdir(parents=True)
    video = Path(args.video)
    shutil.copy(video, work / "videos" / video.name)
    legend = json.loads(video.with_suffix(".json").read_text(encoding="utf-8"))
    hist = Historian(args.historian)

    mqtt_port, http_port = free_port(), free_port()
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "GAUGEVISION_DEVICE": "cpu", "PYTHONIOENCODING": "utf-8",
           "GAUGEVISION_DEMO": "0", "GAUGEVISION_DB": str(work / "gv.db"), "GAUGEVISION_SF_DB": str(work / "sf.db"),
           "GAUGEVISION_VIDEOS_DIR": str(work / "videos"), "GAUGEVISION_INCIDENTS_DIR": str(work / "incidents"),
           "GAUGEVISION_AUTO_SPECS_DIR": str(work / "auto_specs"), "GAUGEVISION_LAN_IP": "127.0.0.1",
           "GAUGEVISION_ADMIN_PASS": PW["admin"], "GAUGEVISION_ENGINEER_PASS": PW["engineer"],
           "GAUGEVISION_OPERATOR_PASS": PW["operator"],
           "GAUGEVISION_MODBUS_ENABLED": "1", "GAUGEVISION_MODBUS_HOST": "127.0.0.1",
           "GAUGEVISION_MODBUS_PORT": "15020", "GAUGEVISION_MODBUS_UNIT_ID": "1",
           "GAUGEVISION_MQTT_ENABLED": "1", "GAUGEVISION_MQTT_HOST": "127.0.0.1",
           "GAUGEVISION_MQTT_PORT": str(mqtt_port), "GAUGEVISION_MQTT_ACK_TIMEOUT": "2.0"}
    broker = Broker(args.amqtt, work, mqtt_port)
    broker.start()
    rx = work / "mqtt_rx.jsonl"
    sink = subprocess.Popen([args.tools_py, str(Path(__file__).with_name("mqtt_sink.py")), str(mqtt_port), str(rx)],
                            stdout=open(work / "sink.log", "w"), stderr=subprocess.STDOUT)
    server = Server(work, env, http_port)
    base = f"https://127.0.0.1:{http_port}"
    t_run0 = time.time()
    t_ms0 = int(t_run0 * 1000)
    try:
        # 1. запуск и авторизация
        boot_s = server.start()
        cli = {r: httpx.Client(base_url=base, verify=False, timeout=60) for r in PW}
        codes = {r: c.post("/api/auth/login", json={"username": r, "password": PW[r]}).status_code for r, c in cli.items()}
        anon = httpx.get(f"{base}/api/instruments", verify=False).status_code
        step(1, "Запуск сервера и авторизация ролей", all(v == 200 for v in codes.values()) and anon == 401,
             boot_s=round(boot_s, 1), login=codes, anonymous=anon)
        eng, op, adm = cli["engineer"], cli["operator"], cli["admin"]

        # 2. видеоисточник
        r = adm.post("/api/cameras", json={"name": "Щит КИП (синтетическое видео)", "type": "video_file",
                                           "source_url": video.name})
        sid = r.json().get("id") if r.status_code == 201 else None
        online = wait_for(lambda: (next(x for x in op.get("/api/cameras").json() if x["id"] == sid)
                                   .get("status") == "online"), 60)
        step(2, "Подключение видеоисточника", r.status_code == 201 and bool(online), source_id=sid, http=r.status_code)

        # 3. обнаружение приборов
        def detect() -> Any:
            d = eng.post(f"/api/sources/{sid}/instruments/detect")
            if d.status_code != 200:
                return None
            j = d.json()
            return j if len(j["candidates"]) >= 8 and any(c.get("is_primary_dial") for c in j["candidates"]) else None
        det = wait_for(detect, 90, 2.0) or {"candidates": [], "frame": {"w": 1280, "h": 720}}
        cands = det["candidates"]
        step(3, "Обнаружение аналоговых приборов на кадре", len(cands) == 8, found=len(cands), expected=8,
             detect=det.get("detect"))

        # 4. регистрация и независимая ручная калибровка
        fw, fh = det["frame"]["w"], det["frame"]["h"]

        def legend_for(anchor: dict[str, Any]) -> dict[str, Any]:
            ax, ay = anchor["cx"], anchor["cy"]
            if ax > 1.5:
                ax, ay = ax / fw, ay / fh
            return min(legend["gauges"], key=lambda g: math.hypot(g["cx"] - ax, g["cy"] - ay))
        own: dict[str, dict[str, Any]] = {}
        unit_type = {"МПа": "pressure", "кПа": "pressure", "°C": "temperature"}
        for c in cands:
            g = legend_for(c["anchor"])
            if c["is_primary_dial"]:
                rr = eng.patch(f"/api/cameras/{sid}", json={"name": g["code"], "unit": g["unit"],
                                                            "gauge_type": unit_type.get(g["unit"], "pressure"),
                                                            "calibration": g["calibration"]})
                # код позиции основного прибора задаётся отдельно (иначе — служебный «КМ-NN» источника)
                eng.patch(f"/api/instruments/{sid}", json={"code": g["code"]})
                own[sid] = g if rr.status_code == 200 else {}
            else:
                rr = eng.post(f"/api/sources/{sid}/instruments", json={
                    "name": g["code"], "code": g["code"], "unit": g["unit"],
                    "gauge_type": unit_type.get(g["unit"], "pressure"), "roi": c["anchor"], "calibration": g["calibration"]})
                if rr.status_code == 201:
                    own[rr.json()["id"]] = g
        insts = {x["id"]: x for x in op.get("/api/instruments").json()}
        slots = {i: insts[i]["modbus_slot"] for i in own if i in insts}
        revs = {i: insts[i]["calibration_rev"] for i in own if i in insts}
        step(4, "Регистрация и независимая ручная калибровка", len(own) == 8 and sorted(slots.values()) == list(range(8)),
             registered=len(own), slots=sorted(slots.values()), calibration_rev=sorted(revs.values()))
        drift_g = legend["gauges"][legend["drift"]["index"]]
        drift_id = next(i for i, g in own.items() if g["index"] == drift_g["index"])
        static_ids = [i for i in own if i != drift_id]

        # 5. показания CV-конвейера
        def all_valid() -> Any:
            m = {x["id"]: x for x in op.get("/api/instruments").json()}
            return m if all((m.get(i) or {}).get("reading", {}) and m[i]["reading"].get("valid") for i in own) else None
        m = wait_for(all_valid, 120, 1.0) or {}
        errs = {}
        for i in static_ids:
            g = own[i]
            rd = (m.get(i) or {}).get("reading") or {}
            if rd.get("raw_value") is not None:
                errs[g["code"]] = round(abs(rd["raw_value"] - g["value_last"]) / (g["v_max"] - g["v_min"]) * 100, 2)
        step(5, "Показания CV-конвейера (синтетический щит, известная истина)",
             bool(m) and len(errs) == 7 and max(errs.values()) < 3.0, err_pct_of_span=errs)

        # 6. история в SQLite
        time.sleep(12)
        con = sqlite3.connect(str(work / "gv.db"))
        per = dict(con.execute("SELECT instrument_id, COUNT(*) FROM readings GROUP BY instrument_id").fetchall())
        con.close()
        step(6, "Сохранение истории в SQLite по приборам", all(per.get(i, 0) > 0 for i in own),
             rows_per_instrument={own[i]["code"]: per.get(i, 0) for i in own})

        # 7. телеметрия для HMI (те же данные, что рисует пульт)
        h = op.get(f"/api/instruments/{static_ids[0]}/history", params={"limit": 20}).json()
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 900))
        tr = op.get(f"/api/instruments/{static_ids[0]}/trend", params={"since": since, "step": 10})
        step(7, "Телеметрия для HMI: история и тренд прибора", len(h) > 0 and tr.status_code == 200,
             history_points=len(h), trend_http=tr.status_code)

        # 8. технологическое предупреждение
        g0 = own[static_ids[0]]
        hw = g0["v_min"] + 0.5 * (g0["value_last"] - g0["v_min"])
        rr = eng.patch(f"/api/instruments/{static_ids[0]}", json={"thresholds": {"h_warn": hw, "hh_alert": g0["v_max"] * 0.999}}) \
            if static_ids[0] != sid else eng.patch(f"/api/cameras/{sid}", json={"thresholds": {"h_warn": hw, "hh_alert": g0["v_max"] * 0.999}})
        ev = wait_for(lambda: [e for e in op.get("/api/events").json()
                               if e["kind"] == "alarm" and e.get("instrument_id") == static_ids[0] and e["level"] == "warning"], 30)
        step(8, "Технологическое предупреждение по уставке H", rr.status_code == 200 and bool(ev),
             event=(ev or [{}])[0].get("id"), needs_ack=not (ev or [{}])[0].get("acked", True))

        # 9–10. прогноз времени до уставки и интервал
        span_d = drift_g["v_max"] - drift_g["v_min"]
        thr = {"h_warn": drift_g["v_min"] + 0.75 * span_d, "hh_alert": drift_g["v_min"] + 0.88 * span_d,
               "lower_enabled": False}
        path = f"/api/cameras/{sid}" if drift_id == sid else f"/api/instruments/{drift_id}"
        eng.patch(path, json={"thresholds": thr})
        t_pred0 = time.time()

        def forecast() -> Any:
            p = op.get(f"/api/predictive/instrument/{drift_id}").json()
            ip = p.get("instrument") or p
            return ip if ip.get("status") == "ok" and ip.get("eta_alert_min") is not None else None
        fc = wait_for(forecast, args.predict_timeout, 10.0) or {}
        now_v = (op.get(f"/api/instruments/{drift_id}/history", params={"limit": 1}).json() or [{}])[-1].get("value")
        # истинное время до HH по закону дрейфа видео (линейно от start до to_frac за minutes)
        d = legend["drift"]
        rate = ((drift_g["v_min"] + d["to_frac"] * span_d) - d["start"]) / (d["minutes"] * 60.0)
        true_eta = (thr["hh_alert"] - now_v) / rate / 60.0 if now_v is not None and rate > 0 else None
        ratio = (fc["eta_alert_min"] / true_eta) if fc.get("eta_alert_min") and true_eta else None
        # критерий: прогноз получен и ETA в пределах 0,5–2 истинного (закон дрейфа видео известен)
        step(9, "Прогноз времени достижения аварийной уставки", bool(fc) and ratio is not None and 0.5 <= ratio <= 2.0,
             eta_alert_min=fc.get("eta_alert_min"), true_eta_min=round(true_eta, 1) if true_eta else None,
             trend=fc.get("trend_class"), waited_s=round(time.time() - t_pred0),
             model={k: (fc.get("model") or {}).get(k) for k in ("method", "slope_per_min", "r2_weighted",
                                                                 "residual_rho1", "damping_tau_min", "n_eff")},
             true_slope_per_min=round(rate * 60, 5) if now_v is not None else None,
             eta_ratio=round(fc["eta_alert_min"] / true_eta, 2) if fc.get("eta_alert_min") and true_eta else None)
        ci = fc.get("eta_alert_ci") or {}
        fh_ = fc.get("forecast_at_horizon") or {}
        step(10, "Прогнозный интервал (PI80/PI95, ДИ ETA)",
             bool(fh_) and fh_.get("lo95") is not None and fh_["lo95"] <= fh_["yhat"] <= fh_["hi95"],
             forecast_at_horizon=fh_, eta_alert_ci=ci)

        # 11. MQTT и Modbus
        pev = wait_for(lambda: [e for e in op.get("/api/events").json() if e["kind"] == "prediction"
                                and e.get("instrument_id") == drift_id], 120, 5.0) or []
        time.sleep(6)
        msgs = [json.loads(x) for x in rx.read_text(encoding="utf-8").splitlines() if x.strip()] if rx.exists() else []
        tele = {mm["payload"].get("instrument_id") for mm in msgs if mm["topic"].endswith("/telemetry")
                and mm["payload"].get("schema") == "gv.telemetry/1"}
        alarm_topics = [mm for mm in msgs if mm["topic"].endswith("/alarm")]
        pred_mqtt = [mm for mm in alarm_topics if mm["payload"].get("kind") == "prediction"]
        regs = modbus_read(0, 32)
        mb_vals = {own[i]["code"]: round(f32(regs[s * 4], regs[s * 4 + 1]), 3) for i, s in slots.items()}
        mb_status = {own[i]["code"]: regs[s * 4 + 2] for i, s in slots.items()}
        pb = modbus_read(3600 + slots[drift_id] * 8, 8)
        step(11, "Передача показаний и событий по MQTT и Modbus",
             tele >= set(own) and bool(alarm_topics) and all(v in (0, 1, 2) for v in mb_status.values())
             and bool(pev) and bool(pred_mqtt),
             mqtt_messages=len(msgs), mqtt_telemetry_instruments=len(tele & set(own)), mqtt_alarm=len(alarm_topics),
             prediction_events=[e["text"] for e in pev], prediction_mqtt=len(pred_mqtt), modbus_values=mb_vals,
             modbus_status=mb_status, modbus_pred_eta=round(f32(pb[0], pb[1]), 1))

        # 12. Ignition (Tag Historian)
        ign: dict[str, Any] = {}
        if hist.path:
            time.sleep(15)
            for i, s in sorted(slots.items(), key=lambda t: t[1]):
                folder = tag_folder(s)
                vals = [v for _, v, q in hist.series(f"GaugeVision/Instruments/{folder}/Value", t_ms0) if v is not None]
                st = [v for _, v, q in hist.series(f"GaugeVision/Instruments/{folder}/Status", t_ms0)]
                g = own[i]
                ign[g["code"]] = {"slot": s, "tag": folder, "points": len(vals),
                                  "last": round(vals[-1], 3) if vals else None, "modbus": mb_vals[g["code"]],
                                  "status_last": st[-1] if st else None}
            hb = hist.series("GaugeVision/System/Heartbeat", t_ms0)
            free_nodata = hist.series(f"GaugeVision/Instruments/{tag_folder(20)}/IsNoData", t_ms0)
            agree = [abs(v["last"] - v["modbus"]) / (own_by_code(own, c)["v_max"] - own_by_code(own, c)["v_min"]) < 0.03
                     for c, v in ign.items() if v["last"] is not None and v["modbus"] is not None
                     and c != own[drift_id]["code"]]
            step(12, "Отображение данных в Ignition 8.3.10 (Tag Historian)",
                 bool(ign) and all(v["points"] > 0 for v in ign.values()) and all(agree) and len(hb) > 3,
                 instruments=ign, heartbeat_points=len(hb),
                 free_slot_isnodata=(free_nodata[-1][1] if free_nodata else None))
        else:
            step(12, "Отображение данных в Ignition 8.3.10", False, reason="Historian не задан — NOT VERIFIED")

        # 13–14. отказ связи и восстановление (останов брокера MQTT)
        sf0 = op.get("/api/architecture/store-forward").json()
        broker.stop()
        t_out = time.time()
        grown = wait_for(lambda: (op.get("/api/architecture/store-forward").json().get("pending_count") or 0) >= 5, 90, 2.0)
        sf_mid = op.get("/api/architecture/store-forward").json()
        # регистры Modbus обновляются циклом раз в 2 с: ждём флаг HR 905 и фиксируем время обнаружения
        flag = wait_for(lambda: modbus_read(904, 2)[1] == 1, 30, 0.5)
        t_flag = time.time() - t_out
        mb_out = modbus_read(904, 2)
        time.sleep(20)
        sf_mid2 = op.get("/api/architecture/store-forward").json()
        step(13, "Имитация отказа связи (брокер MQTT остановлен)", bool(grown) and mb_out[1] == 1,
             pending=sf_mid2.get("pending_count"), hr904_queue=mb_out[0], hr905_outage=mb_out[1],
             hr905_detect_s=round(t_flag, 1) if flag else None,
             outage_s=round(time.time() - t_out))
        rx_before = len(rx.read_text(encoding="utf-8").splitlines()) if rx.exists() else 0
        broker.start()
        t_rec = time.time()
        drained = wait_for(lambda: (op.get("/api/architecture/store-forward").json().get("pending_count") or 0) == 0, 180, 2.0)
        drain_s = time.time() - t_rec
        time.sleep(8)
        msgs = [json.loads(x) for x in rx.read_text(encoding="utf-8").splitlines() if x.strip()]
        seqs = sorted({mm["payload"].get("seq_id") for mm in msgs if isinstance(mm["payload"].get("seq_id"), int)})
        lo = seqs[0] if seqs else 0
        gaps = [s for s in range(lo, seqs[-1] + 1) if s not in set(seqs)] if seqs else []
        sfc = sqlite3.connect(str(work / "sf.db"))
        evicted = sfc.execute("SELECT COUNT(*) FROM sf_overflow_log").fetchone()[0] if sfc.execute(
            "SELECT 1 FROM sqlite_master WHERE name='sf_overflow_log'").fetchone() else 0
        sfc.close()
        mb_rec = modbus_read(904, 2)
        step(14, "Store-and-Forward и автоматическое восстановление", bool(drained) and not gaps and mb_rec[1] == 0,
             drain_s=round(drain_s, 1), received_after=len(msgs) - rx_before, seq_range=[lo, seqs[-1] if seqs else None],
             seq_gaps=len(gaps), evicted=evicted, hr905_after=mb_rec[1])

        # 15–16. план модернизации с обязательным мероприятием и бюджетом
        budget = 450_000
        sol = eng.post("/api/optimizer/solve", json={"budget_rub": budget, "objective": "max_risk_reduction",
                                                      "mandatory_ids": [drift_id], "include_healthy": True,
                                                      "include_frontier": True, "time_limit_s": 3.0}).json()
        plan = eng.post("/api/optimizer/plans", json={"name": "E2E план модернизации", "budget_rub": budget,
                                                       "objective": "max_risk_reduction", "mandatory_ids": [drift_id],
                                                       "include_healthy": True})
        pj = plan.json() if plan.status_code == 200 else {}
        sel = pj.get("selected_ids") or []
        step(15, "Формирование оптимального плана модернизации", plan.status_code == 200 and sol.get("status") in ("optimal", "time_limit"),
             status=sol.get("status"), gap=(sol.get("solver") or {}).get("optimality_gap"), selected=len(sel),
             elapsed_s=sol.get("elapsed_s"), frontier_points=len(sol.get("budget_frontier") or []))
        capex = (pj.get("total_capex_rub") or 0)
        step(16, "Обязательные мероприятия и ограничение бюджета", drift_id in sel and capex <= budget,
             mandatory_included=drift_id in sel, total_capex_rub=capex, budget_rub=budget)

        # 17–18. инженерное ТЗ и сверка с телеметрией
        body = {"period": "12h", "mode": "deterministic", "format": "md", "optimization_plan_id": pj.get("id")}
        md = eng.post("/api/specs/generate", json=body)
        dx = eng.post("/api/specs/generate", json={**body, "format": "docx"})
        prev = eng.post("/api/specs/preview", json=body).json()
        text = md.content.decode("utf-8") if md.status_code == 200 else ""
        xml = ""
        if dx.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(dx.content)) as zf:
                xml = zf.read("word/document.xml").decode("utf-8")
        step(17, "Генерация инженерного ТЗ в DOCX и Markdown", md.status_code == 200 and dx.status_code == 200 and len(xml) > 1000,
             md_bytes=len(md.content), docx_bytes=len(dx.content), doc_number=prev.get("doc_number"))
        codes = {i: (op.get("/api/instruments").json() and next(x for x in op.get("/api/instruments").json() if x["id"] == i)
                     .get("code")) for i in sel}
        con = sqlite3.connect(str(work / "gv.db"))
        n_db = con.execute("SELECT COUNT(*) FROM readings WHERE value IS NOT NULL").fetchone()[0]
        con.close()
        in_md = {c: (c in text) for c in codes.values() if c}
        in_docx = {c: (c in xml) for c in codes.values() if c}
        step(18, "Содержание ТЗ соответствует телеметрии и выбранному плану",
             all(in_md.values()) and all(in_docx.values()) and prev.get("db_samples_count", 0) > 0
             and prev.get("db_samples_count", 0) <= n_db,
             plan_codes_in_md=in_md, plan_codes_in_docx=in_docx, db_samples_in_doc=prev.get("db_samples_count"),
             db_rows=n_db, optimization_applied=prev.get("optimization_applied"))

        # 19. перезапуск: данные сохраняются, Ignition фиксирует обрыв и восстановление
        before = {"instruments": sorted((x["id"], x["modbus_slot"], x["calibration_rev"]) for x in op.get("/api/instruments").json()),
                  "plans": len(op.get("/api/optimizer/plans").json()), "events": len(op.get("/api/events").json())}
        con = sqlite3.connect(str(work / "gv.db"))
        rows_before = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        con.close()
        t_down = time.time()
        server.stop()
        time.sleep(10)
        boot2 = server.start()
        t_ready = time.time()
        for r_, c in cli.items():
            c.post("/api/auth/login", json={"username": r_, "password": PW[r_]})
        after = {"instruments": sorted((x["id"], x["modbus_slot"], x["calibration_rev"]) for x in op.get("/api/instruments").json()),
                 "plans": len(op.get("/api/optimizer/plans").json()), "events": len(op.get("/api/events").json())}
        con = sqlite3.connect(str(work / "gv.db"))
        rows_after = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        con.close()
        valid_again = wait_for(all_valid, 120, 1.0)
        ign_link: dict[str, Any] = {}
        if hist.path:
            time.sleep(15)
            lk = hist.series("GaugeVision/System/LinkConnected", int(t_down * 1000) - 2000)
            down = [t for t, v, _ in lk if v == 0]
            up = [t for t, v, _ in lk if v == 1 and down and t > down[0]]
            ign_link = {"link_lost_after_stop_s": round(down[0] / 1000 - t_down, 1) if down else None,
                        "link_back_after_stop_s": round(up[0] / 1000 - t_down, 1) if up else None,
                        "server_ready_after_stop_s": round(t_ready - t_down, 1), "points": len(lk)}
        step(19, "Перезапуск системы и сохранность данных",
             before["instruments"] == after["instruments"] and after["plans"] == before["plans"]
             and after["events"] >= before["events"] and rows_after >= rows_before and bool(valid_again),
             before=dict(before, instruments=len(before["instruments"])),
             after=dict(after, instruments=len(after["instruments"])), readings=[rows_before, rows_after],
             boot_s=round(boot2, 1), ignition_link=ign_link)
    finally:
        server.stop()
        broker.stop()
        sink.kill()
    res = {"synthetic_source": True, "video": video.name, "legend": legend, "started": t_run0,
           "duration_s": round(time.time() - t_run0, 1), "steps": STEPS,
           "passed": sum(1 for s in STEPS if s["passed"]), "total": len(STEPS)}
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"E2E: {res['passed']}/{res['total']} PASSED")
    return 0 if res["passed"] == res["total"] == 19 else 1


def own_by_code(own: dict[str, dict[str, Any]], code: str) -> dict[str, Any]:
    return next(g for g in own.values() if g["code"] == code)


if __name__ == "__main__":
    sys.exit(main())
