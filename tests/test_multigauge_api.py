"""
Сквозная проверка Multi-Gauge через сервер (этап 3): один источник, щит из 8 приборов.

Кадры синтетического щита (app/panel_sim.py) подаются в брокер кадров источника, дальше работает
штатный путь сервиса: цикл обработки, регистрация приборов через API, отсчёты, уставки и события,
SQLite, Modbus, удаление прибора, возврат к однокамерному режиму и перезапуск сервера.

Запуск (строго CPU):
  CUDA_VISIBLE_DEVICES="" GAUGEVISION_DEVICE=cpu python -B tests/test_multigauge_api.py
"""
from __future__ import annotations

import math
import os
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("GAUGEVISION_DEVICE", "cpu")
_TMP = Path(tempfile.mkdtemp(prefix="gv_mg_api_"))
os.environ["GAUGEVISION_DB"] = str(_TMP / "mg.db")
os.environ["GAUGEVISION_DEMO"] = "0"
os.environ["YOLO_CONFIG_DIR"] = str(_TMP / "yolo_cfg")
# рабочий профиль не принимает стендовые пароли: задаём собственный, как оператор при развёртывании
os.environ["GAUGEVISION_ADMIN_PASS"] = "Mg-Test-" + os.urandom(6).hex()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, panel_sim  # noqa: E402
from app.main import app, service  # noqa: E402

N = 8
UNIT_TYPE = {"МПа": "pressure", "кПа": "pressure", "°C": "temperature"}


class PanelFeeder(threading.Thread):
    """Публикует кадры щита в брокер источника, ~6 кадров/с; можно перекрыть один прибор."""

    def __init__(self, source_id: str, scene: panel_sim.PanelScene) -> None:
        super().__init__(daemon=True)
        self.source_id, self.scene = source_id, scene
        self.occlude: set[int] = set()
        self.stop_evt = threading.Event()
        self.k = 0

    def run(self) -> None:
        while not self.stop_evt.is_set():
            frame, _ = panel_sim.render_panel(self.scene, occlude=set(self.occlude), noise_sigma=1.5, seed=self.k)
            # кадр поступает тем же путём, что от смартфона по WebSocket: воркер отмечает свежесть потока
            worker = service.streams.phone_worker(self.source_id)
            if worker is not None:
                worker.push_frame(frame)
            else:
                service.broker.publish(self.source_id, frame)
            self.k += 1
            time.sleep(0.16)


def wait_for(pred, timeout: float, what: str):
    t0 = time.time()
    while time.time() - t0 < timeout:
        val = pred()
        if val:
            return val
        time.sleep(0.25)
    raise AssertionError(f"не дождались: {what}")


def gauge_for_anchor(scene: panel_sim.PanelScene, anchor: dict) -> panel_sim.PanelGauge:
    return min(scene.gauges, key=lambda g: math.hypot(g.cx - anchor["cx"], g.cy - anchor["cy"]))


def main() -> int:
    scene = panel_sim.make_panel(N, seed=3, size_jitter=0.3)
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"username": "admin", "password": config.ADMIN_PASSWORD}).status_code == 200
        cam = client.post("/api/cameras", json={"name": "Щит КИП-1", "type": "phone_ws"}).json()
        sid = cam["id"]
        assert cam["instrument_id"] == sid and cam["is_primary"] and cam["modbus_slot"] == 0
        feeder = PanelFeeder(sid, scene)
        feeder.start()
        try:
            # однокамерный режим: конвейер находит один (самый крупный) прибор
            wait_for(lambda: (service.last.get(sid) or {}).get("dial_found"), 60, "первый отсчёт источника")

            det = client.post(f"/api/sources/{sid}/instruments/detect").json()
            cands = det["candidates"]
            assert len(cands) == N, f"найдено {len(cands)} циферблатов из {N}"
            prim = [c for c in cands if c["is_primary_dial"]]
            assert len(prim) == 1, prim
            # основной прибор получает шкалу своего циферблата через прежний API камеры
            g0 = gauge_for_anchor(scene, prim[0]["anchor"])
            r = client.patch(f"/api/cameras/{sid}", json={"name": g0.code, "gauge_type": UNIT_TYPE[g0.unit],
                                                          "unit": g0.unit, "calibration": g0.calibration})
            assert r.status_code == 200, r.text

            own: dict[str, panel_sim.PanelGauge] = {sid: g0}
            for c in cands:
                if c["is_primary_dial"]:
                    continue
                g = gauge_for_anchor(scene, c["anchor"])
                r = client.post(f"/api/sources/{sid}/instruments", json={
                    "name": g.code, "code": g.code, "gauge_type": UNIT_TYPE[g.unit], "unit": g.unit,
                    "roi": c["anchor"], "calibration": g.calibration,
                })
                assert r.status_code == 201, r.text
                own[r.json()["id"]] = g
            # повторная регистрация того же циферблата и регистрация основного — отказ
            dup = client.post(f"/api/sources/{sid}/instruments", json={
                "name": "дубль", "roi": cands[-1]["anchor"] if not cands[-1]["is_primary_dial"] else cands[0]["anchor"]})
            assert dup.status_code == 409, dup.text
            dup2 = client.post(f"/api/sources/{sid}/instruments", json={"name": "дубль", "roi": prim[0]["anchor"]})
            assert dup2.status_code == 409, dup2.text
            # повторная детекция помечает все циферблаты зарегистрированными
            det2 = client.post(f"/api/sources/{sid}/instruments/detect").json()
            assert all(c["registered_instrument_id"] for c in det2["candidates"]), det2["candidates"]

            src = client.get(f"/api/sources/{sid}/instruments").json()
            assert src["multi_gauge"] is True and len(src["instruments"]) == N

            def all_valid():
                insts = {x["id"]: x for x in client.get("/api/instruments").json()}
                ok = all((insts.get(i) or {}).get("reading") and insts[i]["reading"].get("valid") for i in own)
                return insts if ok else None
            insts = wait_for(all_valid, 90, "достоверные отсчёты всех приборов щита")
            errs = {}
            for iid, g in own.items():
                rd = insts[iid]["reading"]
                errs[g.code] = abs(rd["raw_value"] - g.value) / (g.v_max - g.v_min)
                assert rd["instrument_id"] == iid and rd["source_id"] == sid and rd["schema"] == "gv.reading/1"
            assert max(errs.values()) < 0.03, errs
            slots = sorted(insts[i]["modbus_slot"] for i in own)
            assert slots == list(range(N)), slots

            # Modbus: значения в слотах приборов
            regs = client.get("/api/scada/modbus/registers", params={"limit": 50}).json()
            rows = {row["instrument_id"]: row for row in regs.get("rows", regs.get("instruments", []))}
            for iid, g in own.items():
                row = rows[iid]
                assert row["modbus_slot"] == insts[iid]["modbus_slot"] and row["status_code"] in (0, 1, 2)
                assert abs(row["value"] - g.value) / (g.v_max - g.v_min) < 0.03

            # уставка дополнительного прибора: тревога адресована прибору и источнику
            sec_id, sec_g = next((i, g) for i, g in own.items() if i != sid)
            hw = sec_g.v_min + 0.5 * (sec_g.value - sec_g.v_min)
            r = client.patch(f"/api/instruments/{sec_id}", json={"thresholds": {"h_warn": hw, "hh_alert": sec_g.v_max * 0.999}})
            assert r.status_code == 200, r.text
            ev = wait_for(lambda: [e for e in client.get("/api/events").json()
                                   if e["kind"] == "alarm" and e.get("instrument_id") == sec_id], 30, "тревога прибора")
            assert ev[0]["source_id"] == sid and ev[0]["level"] == "warning"

            # перекрытие одного прибора: он отказывает, соседи продолжают
            occ_id, occ_g = next((i, g) for i, g in own.items() if i not in (sid, sec_id))
            feeder.occlude = {occ_g.index}
            wait_for(lambda: not (service.last.get(occ_id) or {}).get("valid"), 30, "отказ перекрытого прибора")
            time.sleep(2.0)
            others_valid = [bool((service.last.get(i) or {}).get("valid")) for i in own if i != occ_id]
            assert all(others_valid), others_valid
            occ_state = service.last[occ_id]
            assert occ_state["invalid_reason"], occ_state
            feeder.occlude = set()
            wait_for(lambda: (service.last.get(occ_id) or {}).get("valid"), 40, "восстановление после перекрытия")

            # история: ряды приборов раздельны
            time.sleep(1.5)
            h_sec = client.get(f"/api/instruments/{sec_id}/history", params={"limit": 50}).json()
            h_pri = client.get(f"/api/instruments/{sid}/history", params={"limit": 50}).json()
            # до смены шкалы основной прибор писал отсчёты по старой калибровке: сравниваются только
            # строки текущей ревизии калибровки
            rev = service.instruments[sid]["calibration_rev"]
            h_pri = [x for x in h_pri if x["calibration_rev"] == rev]
            assert rev >= 1 and h_sec and h_pri
            assert all(abs(x["value"] - sec_g.value) / (sec_g.v_max - sec_g.v_min) < 0.05 for x in h_sec)
            assert all(abs(x["value"] - g0.value) / (g0.v_max - g0.v_min) < 0.05 for x in h_pri)
            csv_text = client.get(f"/api/instruments/{sec_id}/export.csv").text
            assert csv_text.count("\n") >= 2 and sec_g.code in csv_text

            # удаление дополнительного прибора: его слот уходит в STALE / NaN
            del_slot = insts[occ_id]["modbus_slot"]
            assert client.delete(f"/api/instruments/{occ_id}").status_code == 204
            assert client.delete(f"/api/instruments/{sid}").status_code == 409
            time.sleep(2.5)
            regs = client.get("/api/scada/modbus/registers", params={"limit": 50}).json()
            raw = service.scada.modbus._regs
            assert raw[del_slot * 4 + 2] == 3 and math.isnan(struct.unpack(">f", struct.pack(">HH", raw[del_slot * 4], raw[del_slot * 4 + 1]))[0])
            assert len(client.get(f"/api/sources/{sid}/instruments").json()["instruments"]) == N - 1
        finally:
            feeder.stop_evt.set()
            feeder.join(timeout=2)
        kept = sorted((i["id"], i["modbus_slot"]) for i in service.instruments.values())

    # перезапуск сервера: приборы, якоря и слоты сохраняются
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": config.ADMIN_PASSWORD})
        after = sorted((i["id"], i["modbus_slot"]) for i in service.instruments.values())
        assert after == kept, (after, kept)
        assert service.is_multi(sid)
        # все дополнительные удалены — источник возвращается к однокамерному режиму
        for iid in [i for i, v in service.instruments.items() if not v["is_primary"]]:
            assert client.delete(f"/api/instruments/{iid}").status_code == 204
        assert not service.is_multi(sid)
        assert [x["id"] for x in client.get("/api/instruments").json()] == [sid]
    print(f"errors (доля шкалы): { {k: round(v, 4) for k, v in errs.items()} }")
    print("ALL MULTI-GAUGE API TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
