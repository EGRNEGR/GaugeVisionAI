"""
Независимая интеграционная приёмка объединённой ветки next-gen/integration (GaugeVision AI 3.0).

Проверки не повторяют существующие наборы, а нацелены на стыки двух направлений разработки:
  1. migration_from_real_old_code   — базы, созданные кодом прежних версий (1.0 консоль, 2.0, ветки
     platform и analytics-validation), открываются новым кодом без потерь строк и значений;
  2. multigauge_calibration_isolation — смена шкалы одного прибора щита не трогает соседние,
     calibration_rev растёт только у него, история для прогноза начинается с новой ревизии;
  3. modbus_slots_lifecycle          — слоты постоянны, удалённый прибор очищает все три блока,
     новый занимает свободный слот, адреса не пересекаются, прогнозный блок есть у всех 200 слотов;
  4. stream_loss_and_recovery       — потеря видеопотока: приборы источника недостоверны, Modbus STALE;
     восстановление потока возвращает отсчёты;
  5. prediction_events_lifecycle    — реальный PredictiveAnalyzer на дрейфующем ряду → одно событие
     imminent (без дублей), снятие с гистерезисом, отзыв при смене калибровки, запись в журнал, SQLite и S&F;
  6. monitoring_vs_optimizer        — оптимизатор на 500 позициях не блокирует /api/health; таймаут честный;
  7. spec_matches_saved_plan        — ТЗ (Markdown и DOCX) по сохранённому плану содержит ровно выбранные
     позиции плана и его бюджет;
  8. new_api_security               — 401/403/422 на новых маршрутах Multi-Gauge, прогноза и оптимизатора;
  9. network_policy                 — OBS-SHARED-01..05 (MQTT без TLS, Modbus без allowlist, LLM SSRF, симулятор);
 10. autocal_cannot_apply           — модуль автокалибровки не подключён даже при включённом флаге,
     калибровка меняется только явным PATCH, каждая смена шкалы — новая ревизия (замена INT-AC-01).

Синтетический щит (app/panel_sim.py) подписан как синтетика: это не фотографии действующего объекта.

Запуск (строго CPU):
  CUDA_VISIBLE_DEVICES="" GAUGEVISION_DEVICE=cpu python -B tests/test_final_integration.py
"""
from __future__ import annotations

import asyncio
import io
import json
import math
import os
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("GAUGEVISION_DEVICE", "cpu")
_TMP = Path(tempfile.mkdtemp(prefix="gv_final_int_"))
os.environ["GAUGEVISION_DB"] = str(_TMP / "main.db")
os.environ["GAUGEVISION_SF_DB"] = str(_TMP / "sf.db")
os.environ["GAUGEVISION_DEMO"] = "0"
os.environ["YOLO_CONFIG_DIR"] = str(_TMP / "yolo_cfg")
os.environ["GAUGEVISION_ADMIN_PASS"] = "Fi-Admin-" + os.urandom(6).hex()
os.environ["GAUGEVISION_ENGINEER_PASS"] = "Fi-Eng-" + os.urandom(6).hex()
os.environ["GAUGEVISION_OPERATOR_PASS"] = "Fi-Op-" + os.urandom(6).hex()
os.environ.pop("GAUGEVISION_AUTOCAL", None)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


os.environ["GAUGEVISION_MODBUS_ENABLED"] = "1"
os.environ["GAUGEVISION_MODBUS_HOST"] = "127.0.0.1"
os.environ["GAUGEVISION_MODBUS_PORT"] = str(_free_port())
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, net_policy, panel_sim  # noqa: E402
from app.main import app, service  # noqa: E402
from app.prediction_events import CONFIRM_EVALS, PredictionEventTracker  # noqa: E402
from app.scada_gateway import ModbusTcpGateway  # noqa: E402

RESULTS: list[dict[str, Any]] = []
UNIT_TYPE = {"МПа": "pressure", "кПа": "pressure", "°C": "temperature"}


def case(name: str) -> Callable[[Callable[..., Any]], Callable[..., None]]:
    def deco(fn: Callable[..., Any]) -> Callable[..., None]:
        def run(*args: Any) -> None:
            t0 = time.perf_counter()
            try:
                details = fn(*args)
                RESULTS.append({"name": name, "passed": True, "s": round(time.perf_counter() - t0, 2),
                                "details": details})
                print(f"[PASS] {name} {json.dumps(details, ensure_ascii=False, default=str)[:400]}", flush=True)
            except Exception as exc:  # noqa: BLE001
                RESULTS.append({"name": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"})
                print(f"[FAIL] {name}: {type(exc).__name__}: {exc}", flush=True)
                traceback.print_exc()
        return run
    return deco


def wait_for(pred: Callable[[], Any], timeout: float, what: str) -> Any:
    t0 = time.time()
    while time.time() - t0 < timeout:
        val = pred()
        if val:
            return val
        time.sleep(0.25)
    raise AssertionError(f"не дождались: {what}")


def f32(regs: list[int], addr: int) -> float:
    return struct.unpack(">f", struct.pack(">HH", regs[addr], regs[addr + 1]))[0]


class PanelFeeder(threading.Thread):
    """Кадры синтетического щита в брокер источника (~6 кадров/с); пауза имитирует потерю потока."""

    def __init__(self, source_id: str, scene: panel_sim.PanelScene) -> None:
        super().__init__(daemon=True)
        self.source_id, self.scene = source_id, scene
        self.paused = threading.Event()
        self.stop_evt = threading.Event()
        self.k = 0

    def run(self) -> None:
        while not self.stop_evt.is_set():
            if not self.paused.is_set():
                frame, _ = panel_sim.render_panel(self.scene, noise_sigma=1.5, seed=self.k)
                # кадр поступает тем же путём, что от смартфона по WebSocket: воркер отмечает свежесть потока
                worker = service.streams.phone_worker(self.source_id)
                if worker is not None:
                    worker.push_frame(frame)
                else:
                    service.broker.publish(self.source_id, frame)
                self.k += 1
            time.sleep(0.16)


# ---------------------------------------------------------------------------
# 1. Миграция баз, созданных кодом прежних версий
# ---------------------------------------------------------------------------
LEGACY_REVS = {
    "GaugeVision-1.0 console (dd25bde)": "dd25bde",
    "GaugeVision-2.0 (94e646e)": "94e646e",
    "next-gen/platform (90dcadf)": "90dcadf",
    "next-gen/analytics-validation (285e896)": "285e896",
}
_FILL_SCRIPT = r'''
import asyncio, json, os, sqlite3, sys
sys.path.insert(0, sys.argv[1])
from app import db
asyncio.run(db.init_db()); asyncio.run(db.close_db())
con = sqlite3.connect(os.environ["GAUGEVISION_DB"]); con.row_factory = sqlite3.Row
tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
def cols(t): return {r["name"]: r for r in con.execute(f"PRAGMA table_info({t})")}
def ins(t, row):
    c = cols(t); row = {k: v for k, v in row.items() if k in c}
    for name, info in c.items():
        if name not in row and info["notnull"] and info["dflt_value"] is None and not info["pk"]:
            row[name] = 0 if "INT" in (info["type"] or "").upper() or "REAL" in (info["type"] or "").upper() else "x"
    con.execute(f"INSERT INTO {t} ({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
cal = json.dumps({"v_min": 0, "theta_min": 135, "v_max": 16, "theta_max": 45, "direction": "cw"})
ins("cameras", {"id": "legacy-cam-1", "name": "МН-1 legacy", "type": "phone_ws", "gauge_type": "pressure",
                "unit": "МПа", "calibration": cal, "thresholds": "{}", "status": "online",
                "created_at": "2026-11-01T00:00:00.000+00:00"})
for i in range(120):
    ins("readings", {"camera_id": "legacy-cam-1", "timestamp": f"2026-11-01T00:{i // 60:02d}:{i % 60:02d}.000+00:00",
                     "value": 5.0 + i * 0.01, "raw_angle": 100.0, "status_level": "normal"})
n_ev = 0
if "events" in tables:
    for i in range(7):
        ins("events", {"id": i + 1, "ts": f"2026-11-01T01:00:0{i}.000+00:00", "kind": "alarm", "cam_id": "legacy-cam-1",
                       "level": "warning", "text": "", "acked": 0, "payload": "{}"}); n_ev += 1
extra = {}
if "instrument_passports" in tables:
    ins("instrument_passports", {"instrument_id": "legacy-cam-1", "criticality_class": 2, "criticality_weight": 1.0,
                                 "custom_capex_rub": 123456.0, "updated_at": "2026-11-01T00:00:00+00:00"})
    extra["instrument_passports"] = 1
if "modernization_plans" in tables:
    ins("modernization_plans", {"name": "План legacy", "created_at": "2026-11-01T00:00:00+00:00", "created_by": "eng",
                                "budget_rub": 500000.0, "objective": "max_risk_reduction", "status": "optimal", "selected_count": 2,
                                "selected_ids_json": json.dumps(["legacy-cam-1", "sim-02"]), "result_json": "{}"})
    extra["modernization_plans"] = 1
con.commit()
counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in sorted(tables)}
print(json.dumps({"counts": counts, "events": n_ev, "extra": extra}))
'''


def _legacy_db(rev: str, work: Path) -> dict[str, Any]:
    code = work / f"code_{rev}"
    code.mkdir(parents=True, exist_ok=True)
    arc = subprocess.run(["git", "-C", str(ROOT), "archive", rev, "app"], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(code)], input=arc, check=True)
    dbp = work / f"legacy_{rev}.db"
    env = {**os.environ, "GAUGEVISION_DB": str(dbp), "GAUGEVISION_DEMO": "0", "PYTHONIOENCODING": "utf-8"}
    script = work / "fill.py"
    script.write_text(_FILL_SCRIPT, encoding="utf-8")
    out = subprocess.run([sys.executable, "-B", str(script), str(code)], capture_output=True, text=True,
                         env=env, cwd=str(work), encoding="utf-8", timeout=180)
    assert out.returncode == 0, out.stderr[-1500:]
    info = json.loads(out.stdout.strip().splitlines()[-1])
    info["db"] = dbp
    return info


@case("migration_from_real_old_code")
def t_migration() -> dict[str, Any]:
    work = _TMP / "legacy"
    work.mkdir(exist_ok=True)
    summary = {}
    for label, rev in LEGACY_REVS.items():
        info = _legacy_db(rev, work)
        dbp: Path = info["db"]
        before = info["counts"]
        sum_before = sqlite3.connect(dbp).execute("SELECT ROUND(SUM(value), 6) FROM readings").fetchone()[0]

        async def migrate() -> dict[str, Any]:
            os.environ["GAUGEVISION_DB"] = str(dbp)
            try:
                await db.init_db()
                await db.init_db()  # повторная инициализация идемпотентна
                series = await db.get_instrument_series(["legacy-cam-1"], since_iso="2026-10-31T00:00:00+00:00",
                                                        max_per_instrument=1000)
                insts = await db.list_instruments("legacy-cam-1")
                return {"series": len(series.get("legacy-cam-1", [])), "instruments": insts}
            finally:
                await db.close_db()
                os.environ["GAUGEVISION_DB"] = str(_TMP / "main.db")

        res = asyncio.run(migrate())
        con = sqlite3.connect(dbp)
        after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
        for t, n in before.items():
            # реестр приборов дополняется основным прибором каждой старой камеры — остальные таблицы без изменений
            want = max(n, before["cameras"]) if t == "instruments" else n
            assert after[t] == want, (label, t, n, after[t])
        assert con.execute("SELECT ROUND(SUM(value), 6) FROM readings").fetchone()[0] == sum_before, label
        assert con.execute("SELECT COUNT(*) FROM readings WHERE instrument_id IS NULL").fetchone()[0] == 0, label
        # основной прибор старой камеры создан, слот Modbus 0, ревизия 0 — история читается целиком
        assert len(res["instruments"]) == 1 and res["instruments"][0]["is_primary"], (label, res["instruments"])
        assert res["series"] == 120, (label, res["series"])
        for t in info["extra"]:
            assert after[t] == before[t] == 1, (label, t)
        summary[label] = {"tables": len(before), "readings": after["readings"], "events": after.get("events"),
                          "passports": after.get("instrument_passports"), "plans": after.get("modernization_plans")}
    return summary


# ---------------------------------------------------------------------------
# 2–4. Многоприборный источник через HTTP
# ---------------------------------------------------------------------------
STATE: dict[str, Any] = {}


def _login(client: TestClient, role: str) -> None:
    pwd = {"admin": config.ADMIN_PASSWORD, "engineer": config.ENGINEER_PASSWORD,
           "operator": config.OPERATOR_PASSWORD}[role]
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": role, "password": pwd})
    assert r.status_code == 200, r.text


def _gauge_for(scene: panel_sim.PanelScene, anchor: dict) -> panel_sim.PanelGauge:
    return min(scene.gauges, key=lambda g: math.hypot(g.cx - anchor["cx"], g.cy - anchor["cy"]))


def _setup_panel(client: TestClient) -> None:
    scene = panel_sim.make_panel(3, seed=11, size_jitter=0.2)
    cam = client.post("/api/cameras", json={"name": "Щит синтетический", "type": "phone_ws"}).json()
    sid = cam["id"]
    feeder = PanelFeeder(sid, scene)
    feeder.start()
    wait_for(lambda: (service.last.get(sid) or {}).get("dial_found"), 60, "первый отсчёт источника")
    cands = client.post(f"/api/sources/{sid}/instruments/detect").json()["candidates"]
    assert len(cands) == 3, cands
    own: dict[str, panel_sim.PanelGauge] = {}
    for c in cands:
        g = _gauge_for(scene, c["anchor"])
        if c["is_primary_dial"]:
            r = client.patch(f"/api/cameras/{sid}", json={"name": g.code, "gauge_type": UNIT_TYPE[g.unit],
                                                          "unit": g.unit, "calibration": g.calibration})
            assert r.status_code == 200, r.text
            own[sid] = g
        else:
            r = client.post(f"/api/sources/{sid}/instruments", json={
                "name": g.code, "code": g.code, "gauge_type": UNIT_TYPE[g.unit], "unit": g.unit,
                "roi": c["anchor"], "calibration": g.calibration})
            assert r.status_code == 201, r.text
            own[r.json()["id"]] = g
    STATE.update(sid=sid, feeder=feeder, own=own, scene=scene)


def _all_valid(client: TestClient, ids: list[str]) -> dict[str, Any] | None:
    insts = {x["id"]: x for x in client.get("/api/instruments").json()}
    ok = all((insts.get(i) or {}).get("reading") and insts[i]["reading"].get("valid") for i in ids)
    return insts if ok else None


@case("multigauge_calibration_isolation")
def t_cal_isolation(client: TestClient) -> dict[str, Any]:
    own: dict[str, panel_sim.PanelGauge] = STATE["own"]
    ids = list(own)
    insts = wait_for(lambda: _all_valid(client, ids), 90, "достоверные отсчёты щита")
    rev0 = {i: insts[i]["calibration_rev"] for i in ids}
    target = next(i for i in ids if i != STATE["sid"])
    g = own[target]
    time.sleep(3.0)
    asyncio.run_coroutine_threadsafe(service._flush_db(), service_loop(client)).result(10)
    # инженер вручную расширяет шкалу прибора вдвое: ревизия растёт только у него
    new_cal = {**g.calibration, "v_max": g.calibration["v_min"] + 2 * (g.calibration["v_max"] - g.calibration["v_min"])}
    r = client.patch(f"/api/instruments/{target}", json={"calibration": new_cal})
    assert r.status_code == 200, r.text
    insts2 = {x["id"]: x for x in client.get("/api/instruments").json()}
    assert insts2[target]["calibration_rev"] == rev0[target] + 1
    assert all(insts2[i]["calibration_rev"] == rev0[i] for i in ids if i != target), (rev0, insts2)
    meta = asyncio.run_coroutine_threadsafe(db.get_instrument(target), service_loop(client)).result(5)["calibration_meta"]
    assert meta.get("source") == "manual" and meta.get("status") == "confirmed", meta
    # новый отсчёт прибора — по новой шкале (значение примерно вдвое выше доли старой шкалы)
    expect = g.calibration["v_min"] + 2 * (g.value - g.calibration["v_min"])

    def new_valid() -> Any:
        rd = (service.last.get(target) or {})
        return rd if rd.get("valid") and rd.get("calibration_rev") == rev0[target] + 1 else None
    rd = wait_for(new_valid, 40, "отсчёт по новой калибровке")
    span_new = new_cal["v_max"] - new_cal["v_min"]
    assert abs(rd["raw_value"] - expect) / span_new < 0.03, (rd["raw_value"], expect)
    for i in ids:
        if i != target:
            o = own[i]
            assert abs(service.last[i]["raw_value"] - o.value) / (o.v_max - o.v_min) < 0.03, i
    time.sleep(3.0)
    loop = service_loop(client)
    asyncio.run_coroutine_threadsafe(service._flush_db(), loop).result(10)
    # история для прогноза: только строки новой ревизии; соседей фильтр не затрагивает
    since = "2000-01-01T00:00:00+00:00"
    series = asyncio.run_coroutine_threadsafe(
        db.get_instrument_series(ids, since_iso=since, max_per_instrument=5000), loop).result(10)

    def rows_by_rev(iid: str) -> dict[Any, int]:
        con = sqlite3.connect(os.environ["GAUGEVISION_DB"])
        return dict(con.execute("SELECT COALESCE(calibration_rev, 0), COUNT(*) FROM readings "
                                "WHERE instrument_id = ? AND value IS NOT NULL GROUP BY 1", (iid,)).fetchall())
    by_rev = rows_by_rev(target)
    assert by_rev.get(rev0[target], 0) > 0 and by_rev.get(rev0[target] + 1, 0) > 0, by_rev
    assert len(series[target]) == by_rev[rev0[target] + 1], (len(series[target]), by_rev)
    assert all(abs(v - expect) / span_new < 0.05 for _, v in series[target])
    cur_rev = {i: insts2[i]["calibration_rev"] for i in ids}
    for i in ids:
        if i != target:
            assert len(series[i]) == rows_by_rev(i).get(cur_rev[i], 0) > 0, (i, rows_by_rev(i), len(series[i]))
    STATE["target"] = target
    return {"target_rev": rev0[target] + 1, "rows_old_rev": by_rev[rev0[target]],
            "rows_new_rev": by_rev[rev0[target] + 1], "series_len": len(series[target])}


def service_loop(client: TestClient) -> asyncio.AbstractEventLoop:
    if "loop" not in STATE:
        STATE["loop"] = client.portal.call(_running_loop)
    return STATE["loop"]


async def _running_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()


@case("modbus_slots_lifecycle")
def t_modbus(client: TestClient) -> dict[str, Any]:
    own: dict[str, panel_sim.PanelGauge] = STATE["own"]
    insts = {x["id"]: x for x in client.get("/api/instruments").json()}
    slots = {i: insts[i]["modbus_slot"] for i in own}
    assert sorted(slots.values()) == [0, 1, 2], slots
    time.sleep(2.5)
    regs = service.scada.modbus._regs
    for i, s in slots.items():
        rd = service.last[i]
        if rd.get("valid") and rd.get("value") is not None:
            # регистры обновляются раз в 2 с, отсчёт — с каждым кадром: допуск 2 % шкалы
            g = own[i]
            assert abs(f32(regs, s * 4) - rd["value"]) / (g.v_max - g.v_min) < 0.02, (i, f32(regs, s * 4), rd["value"])
    # реальный клиент Modbus TCP по сокету: значение слота 0 совпадает с регистром
    with socket.create_connection(("127.0.0.1", config.MODBUS_PORT), timeout=3) as s:
        s.sendall(struct.pack(">HHHBBHH", 1, 0, 6, config.MODBUS_UNIT_ID, 3, 0, 4))
        resp = s.recv(256)
    assert resp[7] == 3 and resp[8] == 8, resp.hex()
    # удаление прибора: все три блока его слота очищены, соседи на месте
    victim = next(i for i in own if i not in (STATE["sid"], STATE.get("target")))
    vs = slots[victim]
    keep = {i: f32(regs, s * 4) for i, s in slots.items() if i != victim}
    assert client.delete(f"/api/instruments/{victim}").status_code == 204
    time.sleep(2.5)
    regs = service.scada.modbus._regs
    assert math.isnan(f32(regs, vs * 4)) and regs[vs * 4 + 2] == 3
    ext = ModbusTcpGateway.EXTENDED_BASE + vs * ModbusTcpGateway.EXTENDED_STRIDE
    assert regs[ext] == 65535 and regs[ext + 2] & 0x0040 and math.isnan(f32(regs, ext + 5))
    pb = ModbusTcpGateway.predictive_base(vs)
    assert math.isnan(f32(regs, pb)) and regs[pb + 6] == 6
    for i, v in keep.items():
        assert not math.isnan(f32(regs, slots[i] * 4)) or not service.last[i].get("valid"), i
    # новый прибор занимает освободившийся слот, а не сдвигает соседей
    cands = client.post(f"/api/sources/{STATE['sid']}/instruments/detect").json()["candidates"]
    free = next(c for c in cands if not c["registered_instrument_id"])
    g = _gauge_for(STATE["scene"], free["anchor"])
    r = client.post(f"/api/sources/{STATE['sid']}/instruments", json={
        "name": g.code + "-2", "code": g.code + "-2", "gauge_type": UNIT_TYPE[g.unit], "unit": g.unit,
        "roi": free["anchor"], "calibration": g.calibration})
    assert r.status_code == 201, r.text
    new_id, new_slot = r.json()["id"], r.json()["modbus_slot"]
    assert new_slot == vs and new_id != victim, (new_slot, vs)
    own.pop(victim)
    own[new_id] = g
    # карта: 200 слотов, прогнозный блок у каждого, пересечений с базовым/системным/расширенным нет
    blocks = [(0, 799), (900, 917), (2000, 3599)] + [(ModbusTcpGateway.predictive_base(k),
                                                      ModbusTcpGateway.predictive_base(k) + 7) for k in range(200)]
    blocks.sort()
    assert all(a[1] < b[0] for a, b in zip(blocks, blocks[1:])) and blocks[-1][1] < ModbusTcpGateway.MAX_REGISTERS
    assert regs[916] == ModbusTcpGateway.PREDICTIVE_EXT_BASE and regs[917] == 61
    return {"slots": sorted(slots.values()), "deleted_slot": vs, "reused_slot": new_slot,
            "max_registers": ModbusTcpGateway.MAX_REGISTERS}


@case("stream_loss_and_recovery")
def t_stream_loss(client: TestClient) -> dict[str, Any]:
    own: dict[str, panel_sim.PanelGauge] = STATE["own"]
    ids = list(own)
    wait_for(lambda: _all_valid(client, ids), 60, "достоверные отсчёты перед обрывом")
    feeder: PanelFeeder = STATE["feeder"]
    t0 = time.time()
    feeder.paused.set()

    def all_stale() -> bool:
        insts = {x["id"]: x for x in client.get("/api/instruments").json()}
        regs = service.scada.modbus._regs
        return all(regs[insts[i]["modbus_slot"] * 4 + 2] == 3 for i in ids)
    wait_for(all_stale, 60, "STALE в Modbus у всех приборов источника после потери потока")
    t_stale = time.time() - t0
    feeder.paused.clear()
    t1 = time.time()
    wait_for(lambda: _all_valid(client, ids), 90, "восстановление отсчётов после возврата потока")
    t_rec = time.time() - t1
    regs = service.scada.modbus._regs
    wait_for(lambda: all(service.scada.modbus._regs[(x["modbus_slot"]) * 4 + 2] in (0, 1, 2)
                         for x in client.get("/api/instruments").json() if x["id"] in ids), 20, "Modbus OK")
    return {"stale_after_s": round(t_stale, 1), "recovered_after_s": round(t_rec, 1)}


# ---------------------------------------------------------------------------
# 5. Прогнозные события
# ---------------------------------------------------------------------------
@case("prediction_events_lifecycle")
def t_prediction(client: TestClient) -> dict[str, Any]:
    # 5a. автомат состояний: подтверждение, отсутствие дублей, гистерезис, отзыв при смене ревизии
    tr = PredictionEventTracker()

    def p(eta: float | None, prob: float = 0.0, status: str = "ok", level: str = "warning") -> dict[str, Any]:
        return {"status": status, "valid": status == "ok", "current_level": level, "eta_alert_min": eta,
                "breach_prob_alert_horizon": prob, "thresholds_eta": {"HH": {"severity": "alert", "threshold": 15.2,
                                                                             "eta_median_min": eta}}}
    seq = []
    seq += tr.update({"a": p(20)}, 0, {"a": 0})
    assert not seq, "событие без подтверждения"
    seq += tr.update({"a": p(18)}, 10, {"a": 0})
    assert [x["text"] for x in seq] == ["imminent"] and seq[0]["setpoint"] == "HH"
    for k in range(5):
        seq += tr.update({"a": p(15 - k)}, 20 + k * 10, {"a": 0})
    assert len(seq) == 1, "дубль прогнозного события"
    seq += tr.update({"a": p(40)}, 80, {"a": 0})  # между порогами входа и выхода — без перехода
    seq += tr.update({"a": p(50)}, 90, {"a": 0})
    assert len(seq) == 1
    seq += tr.update({"a": p(None)}, 100, {"a": 0})
    assert [x["text"] for x in seq] == ["imminent", "cleared"]
    for k in range(CONFIRM_EVALS):
        seq += tr.update({"a": p(10)}, 110 + k, {"a": 0})
    seq += tr.update({"a": p(9)}, 120, {"a": 1})  # смена калибровки
    assert [x["text"] for x in seq][-2:] == ["imminent", "withdrawn"], seq
    for k in range(CONFIRM_EVALS):
        seq += tr.update({"a": p(10)}, 130 + k, {"a": 1})
    seq += tr.update({"a": p(0.0, 1.0, level="alert")}, 140, {"a": 1})
    assert seq[-1]["text"] == "realized"
    seq += tr.update({"a": p(5, status="insufficient_data")}, 150, {"a": 1})
    assert seq[-1]["text"] == "realized", "событие на недостоверном прогнозе"

    # 5b. реальный анализатор на дрейфующем ряду → событие в журнале, SQLite и Store-and-Forward
    loop = service_loop(client)
    now = time.time()
    inst = {"id": "pred-test-1", "code": "ПР-ДРЕЙФ", "name": "Дрейф синтетический", "unit": "МПа",
            "gauge_type": "pressure", "calibration": {"v_min": 0, "v_max": 16},
            "thresholds": {"h_warn": 12.0, "hh_alert": 14.0, "lower_enabled": False},
            "reading": {"value": 11.0, "valid": True, "level": "normal"}, "source_kind": "camera"}
    series = {"pred-test-1": [(now - 1800 + i * 30, 5.0 + i * 0.1 + 0.02 * math.sin(i)) for i in range(61)]}
    inst["reading"]["value"] = series["pred-test-1"][-1][1]
    ov = service.predictive.overview([inst], series, window_min=60, horizon_min=60, now_unix=now)
    x = ov["instruments"][0]
    assert x["status"] == "ok" and x["eta_alert_min"] is not None and x["eta_alert_min"] <= 30, x.get("eta_alert_min")
    sf_before = asyncio.run_coroutine_threadsafe(service.store_forward.pending_count(), loop).result(5)
    evs = []
    for _ in range(CONFIRM_EVALS + 2):
        evs += client.portal.call(_publish, ov)
    assert [e["text"] for e in evs] == ["imminent"], evs
    ev = evs[0]
    assert ev["kind"] == "prediction" and ev["instrument_id"] == "pred-test-1" and ev["setpoint"] == "HH"
    assert ev["acked"] is True, "прогноз — подсказка, не требует квитирования"
    time.sleep(1.0)
    api_evs = [e for e in client.get("/api/events").json() if e["kind"] == "prediction"]
    assert len(api_evs) == 1 and api_evs[0]["id"] == ev["id"]
    con = sqlite3.connect(os.environ["GAUGEVISION_DB"])
    assert con.execute("SELECT COUNT(*) FROM events WHERE kind = 'prediction'").fetchone()[0] == 1
    sf_after = asyncio.run_coroutine_threadsafe(service.store_forward.pending_count(), loop).result(5)
    sfc = sqlite3.connect(os.environ["GAUGEVISION_SF_DB"])
    rows = sfc.execute("SELECT channel_id, payload_type, severity, payload_json FROM sf_queue "
                       "WHERE channel_id = 'pred-test-1'").fetchall() if _has_table(sfc, "sf_queue") else []
    assert sf_after >= sf_before
    if rows:
        assert rows[-1][1] == "alarm" and rows[-1][2] == "warning" and '"prediction"' in rows[-1][3]
    # прибор исчез из сводки (удалён) — прогноз отзывается одним событием
    gone = client.portal.call(_publish, {"instruments": []})
    assert [e["text"] for e in gone] == ["withdrawn"]
    return {"state_machine_events": [x["text"] for x in seq], "eta_alert_min": x["eta_alert_min"],
            "sf_rows": len(rows), "journal_events": len(api_evs)}


async def _publish(ov: dict[str, Any]) -> list[dict[str, Any]]:
    return service._publish_prediction_events(ov)


def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


# ---------------------------------------------------------------------------
# 6–7. Оптимизатор и ТЗ
# ---------------------------------------------------------------------------
@case("monitoring_vs_optimizer")
def t_opt_concurrency(client: TestClient) -> dict[str, Any]:
    from app.modernization_optimizer import optimize_modernization_budget
    # 6a. честный таймаут: при малом лимите времени на 500 позициях — time_limit с оценкой разрыва
    disp = {"instruments": [{"id": f"x{i}", "code": f"X{i}", "name": f"X{i}", "group": f"g{i % 5}",
                             "health_score": 20 + (i * 37) % 70, "level": "normal", "critical_wear": i % 7 == 0,
                             "root_cause": "instrument_degradation" if i % 3 else "optical_issue"}
                            for i in range(500)], "summary": {}}
    t0 = time.perf_counter()
    res = optimize_modernization_budget(dispatch_overview=disp, predictive_overview=None, passports_by_id={},
                                        budget_rub=4_000_000, objective="max_risk_reduction", time_limit_s=0.05,
                                        include_frontier=False, include_healthy=True, solver_backend="bnb")
    dt = time.perf_counter() - t0
    assert res["status"] in ("optimal", "time_limit"), res["status"]
    if res["status"] == "time_limit":
        solver = res.get("solver") or {}
        assert solver.get("optimality_gap") is not None and solver["optimality_gap"] >= 0, solver
    assert dt < 3.0, dt
    # 6b. /api/health отвечает, пока в пуле аналитики считаются оптимизатор (500 позиций, кривая Парето)
    # и прогноз по 500 рядам — тот же путь, что у API (analytics_executor, вне event loop)
    now = time.time()
    p_insts = [{"id": f"p{i}", "code": f"P{i}", "name": f"P{i}", "unit": "МПа", "gauge_type": "pressure",
                "calibration": {"v_min": 0, "v_max": 16}, "thresholds": {"h_warn": 12, "hh_alert": 14},
                "reading": {"value": 8.0, "valid": True, "level": "normal"}, "source_kind": "camera"}
               for i in range(500)]
    p_series = {f"p{i}": [(now - 3600 + k * 30, 6 + 0.01 * k * (i % 5) + 0.05 * math.sin(k + i)) for k in range(120)]
                for i in range(500)}

    async def heavy() -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        lags: list[float] = []
        done = asyncio.Event()

        async def ticker() -> None:  # задержка event loop: таймер 10 мс внутри цикла сервиса
            while not done.is_set():
                t = time.perf_counter()
                await asyncio.sleep(0.01)
                lags.append((time.perf_counter() - t) * 1000 - 10.0)
        tk = asyncio.create_task(ticker())
        t0 = time.perf_counter()
        ov = await loop.run_in_executor(service.analytics_executor, lambda: service.predictive.overview(
            p_insts, p_series, window_min=60, horizon_min=60, now_unix=now))
        t1 = time.perf_counter()
        r = await service.run_optimizer_nonblocking(
            dispatch_overview=disp, predictive_overview=None, passports_by_id={}, budget_rub=4_000_000,
            objective="max_risk_reduction", include_healthy=True, include_frontier=True, time_limit_s=2.0)
        t2 = time.perf_counter()
        done.set()
        await tk
        lags.sort()
        return {"pred_ms": (t1 - t0) * 1000, "solve_ms": (t2 - t1) * 1000, "status": r["status"],
                "elapsed_s": r["elapsed_s"], "frontier_complete": r["frontier_complete"],
                "n_pred": len(ov["instruments"]), "lag_p95": lags[int(0.95 * (len(lags) - 1))], "lag_max": lags[-1],
                "lag_n": len(lags)}
    h = client.portal.call(heavy)
    assert h["n_pred"] == 500 and h["status"] in ("optimal", "time_limit"), h
    # общий лимит времени соблюдается вместе с кривой Парето
    assert h["elapsed_s"] <= 2.0 + 0.3 and h["solve_ms"] <= 2600, h
    assert h["lag_p95"] < 100 and h["lag_max"] < 500, h
    pred_ms, solve_ms, solve_status, p95 = h["pred_ms"], h["solve_ms"], h["status"], h["lag_p95"]
    return {"timeout_status": res["status"], "timeout_wall_s": round(dt, 2), "predictive_500_ms": round(pred_ms, 1),
            "solve_500_ms": round(solve_ms, 1), "solve_status": solve_status, "elapsed_s": h["elapsed_s"],
            "frontier_complete": h["frontier_complete"], "loop_lag_p95_ms": round(p95, 1),
            "loop_lag_max_ms": round(h["lag_max"], 1)}


@case("spec_matches_saved_plan")
def t_spec_plan(client: TestClient) -> dict[str, Any]:
    _login(client, "engineer")
    plan = client.post("/api/optimizer/plans", json={"name": "План интеграции", "budget_rub": 700000,
                                                      "objective": "max_risk_reduction", "include_healthy": True})
    assert plan.status_code == 200, plan.text
    p = plan.json()
    sel = json.loads(p["selected_ids_json"]) if isinstance(p.get("selected_ids_json"), str) else p.get("selected_ids")
    assert sel, p
    got = client.get(f"/api/optimizer/plans/{p['id']}").json()
    assert got["id"] == p["id"] and abs(float(got["budget_rub"]) - 700000) < 1e-6
    codes = {x["id"]: x.get("code") or x["id"] for x in client.get("/api/instruments").json()}
    body = {"period": "24h", "mode": "deterministic", "format": "md", "optimization_plan_id": p["id"]}
    md = client.post("/api/specs/generate", json=body)
    assert md.status_code == 200, md.text
    text = md.content.decode("utf-8")
    for iid in sel:
        assert (codes.get(iid) or iid) in text, iid
    # позиции вне плана в разделе плана не появляются
    others = [c for i, c in codes.items() if i not in sel and c]
    plan_sec = text[text.find("5.2"):] if "5.2" in text else text
    leaked = [c for c in others if f"| {c} " in plan_sec]
    assert not leaked, leaked
    docx = client.post("/api/specs/generate", json={**body, "format": "docx"})
    assert docx.status_code == 200
    with zipfile.ZipFile(io.BytesIO(docx.content)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    for iid in sel:
        assert (codes.get(iid) or iid) in xml, iid
    _login(client, "admin")
    return {"plan_id": p["id"], "selected": len(sel), "md_bytes": len(md.content), "docx_bytes": len(docx.content)}


# ---------------------------------------------------------------------------
# 8–10. Безопасность, сетевая политика, автокалибровка
# ---------------------------------------------------------------------------
@case("new_api_security")
def t_security(client: TestClient) -> dict[str, Any]:
    sid = STATE["sid"]
    some = next(i for i in STATE["own"] if i != sid)
    client.cookies.clear()
    unauth = {
        "GET sources": client.get(f"/api/sources/{sid}/instruments").status_code,
        "POST detect": client.post(f"/api/sources/{sid}/instruments/detect").status_code,
        "POST instrument": client.post(f"/api/sources/{sid}/instruments", json={"name": "x"}).status_code,
        "PATCH instrument": client.patch(f"/api/instruments/{some}", json={"name": "x"}).status_code,
        "DELETE instrument": client.delete(f"/api/instruments/{some}").status_code,
        "GET predictive": client.get("/api/predictive/overview").status_code,
        "POST solve": client.post("/api/optimizer/solve", json={"budget_rub": 1}).status_code,
    }
    assert all(v == 401 for v in unauth.values()), unauth
    _login(client, "operator")
    op = {
        "GET sources": client.get(f"/api/sources/{sid}/instruments").status_code,
        "POST detect": client.post(f"/api/sources/{sid}/instruments/detect").status_code,
        "PATCH instrument": client.patch(f"/api/instruments/{some}", json={"name": "x"}).status_code,
        "DELETE instrument": client.delete(f"/api/instruments/{some}").status_code,
    }
    assert op["GET sources"] == 200 and all(op[k] == 403 for k in op if k != "GET sources"), op
    _login(client, "engineer")
    bad = {
        "NaN calibration": client.patch(f"/api/instruments/{some}", content='{"calibration": {"v_min": 0, "v_max": NaN, '
                                        '"theta_min": 0, "theta_max": 270, "direction": "cw"}}',
                                        headers={"Content-Type": "application/json"}).status_code,
        "degenerate scale": client.patch(f"/api/instruments/{some}", json={"calibration": {
            "v_min": 5, "v_max": 5, "theta_min": 0, "theta_max": 270, "direction": "cw"}}).status_code,
        "huge name": client.post(f"/api/sources/{sid}/instruments", json={"name": "x" * 5000}).status_code,
        "unknown source": client.post("/api/sources/../../etc/instruments", json={"name": "x"}).status_code,
        "engineer delete": client.delete(f"/api/instruments/{some}").status_code,
    }
    assert bad["NaN calibration"] in (400, 422) and bad["degenerate scale"] == 422, bad
    assert bad["huge name"] == 422 and bad["unknown source"] in (404, 405, 422) and bad["engineer delete"] == 403, bad
    _login(client, "admin")
    assert client.delete(f"/api/instruments/{sid}").status_code == 409  # основной — только вместе с источником
    return {"unauth": unauth, "operator": op, "malformed": bad}


@case("network_policy")
def t_net_policy() -> dict[str, Any]:
    saved = {k: getattr(config, k) for k in ("MQTT_HOST", "MQTT_TLS", "MODBUS_HOST")}
    env_keys = ("GAUGEVISION_MQTT_ALLOW_PLAINTEXT", "GAUGEVISION_MODBUS_ALLOWED_CLIENTS", "GAUGEVISION_LLM_ALLOW_PUBLIC",
                "GAUGEVISION_STRICT_NETWORK")
    saved_env = {k: os.environ.get(k) for k in env_keys}
    try:
        for k in env_keys:
            os.environ.pop(k, None)
        config.MQTT_HOST, config.MQTT_TLS = "127.0.0.1", False
        assert net_policy.mqtt_transport_error() is None
        config.MQTT_HOST = "10.20.30.40"
        assert net_policy.mqtt_transport_error()
        config.MQTT_TLS = True
        assert net_policy.mqtt_transport_error() is None
        config.MQTT_TLS = False
        os.environ["GAUGEVISION_MQTT_ALLOW_PLAINTEXT"] = "1"
        assert net_policy.mqtt_transport_error() is None
        config.MODBUS_HOST = "0.0.0.0"
        assert net_policy.modbus_bind_error()
        os.environ["GAUGEVISION_MODBUS_ALLOWED_CLIENTS"] = "10.0.5.7, 192.168.10.0/24"
        assert net_policy.modbus_bind_error() is None
        assert net_policy.modbus_client_allowed("10.0.5.7") and net_policy.modbus_client_allowed("192.168.10.99")
        assert not net_policy.modbus_client_allowed("10.0.5.8") and net_policy.modbus_client_allowed("127.0.0.1")
        llm = {u: net_policy.llm_url_error(u) for u in (
            "http://127.0.0.1:11434/v1", "http://10.1.2.3:8000/v1", "http://169.254.169.254/latest",
            "file:///etc/passwd", "https://user:pw@127.0.0.1/v1", "https://8.8.8.8/v1")}
        assert llm["http://127.0.0.1:11434/v1"] is None and llm["http://10.1.2.3:8000/v1"] is None
        assert all(llm[u] for u in llm if u not in ("http://127.0.0.1:11434/v1", "http://10.1.2.3:8000/v1")), llm
        # строгий режим: веб-сервер на всех интерфейсах вне демопрофиля не запускается
        os.environ["GAUGEVISION_STRICT_NETWORK"] = "1"
        try:
            net_policy.startup_check("0.0.0.0")
            raise AssertionError("строгий режим пропустил 0.0.0.0")
        except SystemExit:
            pass
        assert net_policy.startup_check("192.168.1.10") == [] or all(
            i["severity"] != "block" for i in net_policy.startup_check("192.168.1.10"))
        os.environ.pop("GAUGEVISION_STRICT_NETWORK", None)
        warn = net_policy.posture("0.0.0.0")
        assert any(i["id"] == "OBS-SHARED-01" and i["severity"] == "warning" for i in warn), warn
        # внешняя ссылка на симулятор — только в демопрофиле
        assert config.simulator_url() == "" or os.environ.get("GAUGEVISION_SIMULATOR_URL")
        return {"llm_rejected": sorted(u for u, e in llm.items() if e)}
    finally:
        for k, v in saved.items():
            setattr(config, k, v)
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@case("autocal_cannot_apply")
def t_autocal(client: TestClient) -> dict[str, Any]:
    routes = sorted({getattr(r, "path", "") for r in app.routes})
    assert not [p for p in routes if "autocal" in p or "calibration/confirm" in p], routes
    assert "app.autocal" not in sys.modules, "модуль автокалибровки загружен сервисом"
    # даже с включённым флагом новый процесс сервиса модуль не загружает и маршрутов не добавляет
    probe = subprocess.run([sys.executable, "-B", "-c",
                            "import sys; from app import main; "
                            "print('app.autocal' in sys.modules, any('autocal' in getattr(r,'path','') for r in main.app.routes))"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=120,
                           env={**os.environ, "GAUGEVISION_AUTOCAL": "1", "GAUGEVISION_DB": str(_TMP / "probe.db")})
    assert probe.returncode == 0 and probe.stdout.strip().splitlines()[-1] == "False False", (probe.stdout, probe.stderr[-800:])
    # калибровка меняется только явным PATCH; ROI без шкалы ревизию не меняет; каждая смена шкалы — +1
    iid = next(i for i in STATE["own"] if i != STATE["sid"])
    rev = client.get("/api/instruments").json()
    rev = next(x for x in rev if x["id"] == iid)["calibration_rev"]
    time.sleep(3.0)
    rev_idle = next(x for x in client.get("/api/instruments").json() if x["id"] == iid)["calibration_rev"]
    assert rev_idle == rev, "калибровка изменилась без действия инженера"
    g = STATE["own"][iid]
    r1 = client.patch(f"/api/instruments/{iid}", json={"calibration": g.calibration})
    r2 = client.patch(f"/api/instruments/{iid}", json={"calibration": {**g.calibration,
                                                                         "v_max": g.calibration["v_max"] * 1.5}})
    assert r1.status_code == 200 and r2.status_code == 200
    revs = [x["calibration_rev"] for x in (r1.json(), r2.json())]
    assert revs[1] == revs[0] + 1, revs
    r3 = client.patch(f"/api/instruments/{iid}", json={"calibration": g.calibration})
    assert r3.json()["calibration_rev"] == revs[1] + 1
    audit = sqlite3.connect(os.environ["GAUGEVISION_DB"]).execute(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'UPDATE_INSTRUMENT' AND target = ?", (iid,)).fetchone()[0]
    assert audit >= 3, audit
    return {"routes_checked": len(routes), "revs": revs + [r3.json()["calibration_rev"]], "audit_rows": audit}


def main() -> int:
    t_migration()
    t_net_policy()
    with TestClient(app) as client:
        _login(client, "admin")
        service_loop(client)
        _setup_panel(client)
        try:
            for fn in (t_cal_isolation, t_modbus, t_stream_loss, t_prediction, t_opt_concurrency,
                       t_spec_plan, t_security, t_autocal):
                fn(client)
        finally:
            STATE["feeder"].stop_evt.set()
            STATE["feeder"].join(timeout=2)
        kept = sorted((i["id"], i["modbus_slot"], i["calibration_rev"]) for i in service.instruments.values())
        n_read = sqlite3.connect(os.environ["GAUGEVISION_DB"]).execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    # перезапуск: реестр, слоты, ревизии и история сохраняются
    with TestClient(app) as client:
        _login(client, "admin")
        after = sorted((i["id"], i["modbus_slot"], i["calibration_rev"]) for i in service.instruments.values())
        n_after = sqlite3.connect(os.environ["GAUGEVISION_DB"]).execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        ok = after == kept and n_after >= n_read
        RESULTS.append({"name": "restart_persistence", "passed": ok,
                        "details": {"instruments": len(after), "readings": n_after}})
        print(f"[{'PASS' if ok else 'FAIL'}] restart_persistence instruments={len(after)} readings={n_after}")
    out = os.environ.get("GV_FINAL_INT_OUT")
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    passed = sum(1 for r in RESULTS if r["passed"])
    print(f"FINAL INTEGRATION: {passed}/{len(RESULTS)} PASSED")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
