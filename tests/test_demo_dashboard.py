"""
Регрессионные проверки демонстрационного пульта GaugeVision AI:
- 36 устойчивых позиций (1 phone_cv + 35 simulated) и идемпотентность QR;
- пороговые границы зон (равенство LL/L/H/HH, отключённые нижние зоны, валидация);
- переход через 0/360°, нулевой размах и отсечка неверного направления CW/CCW;
- изоляция источников, реальный CV-прогон 13,0 -> 14,7 -> 15,7 -> пауза -> 13,0 МПа по WSS;
- адресное идемпотентное квитирование событий и связь возврата в норму с отклонением;
- фильтрация экспорта CSV по текущему показу и совместимость старого маршрута.

Запуск:
  py -3.12 tests/test_demo_dashboard.py
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"
os.environ["GAUGEVISION_DEMO"] = "1"
os.environ["GAUGEVISION_STALE_SECONDS"] = "2.5"

_tmp_dir = tempfile.TemporaryDirectory(prefix="gv_demo_test_")
os.environ["GAUGEVISION_DB"] = str(Path(_tmp_dir.name) / "demo_test.db")
os.environ["YOLO_CONFIG_DIR"] = str(Path(_tmp_dir.name) / "yolo_cfg")

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app import config, vision
config.configure_runtime(demo=True, db_path=os.environ["GAUGEVISION_DB"], device="cpu")
from app.main import app  # noqa: E402


def render_mtp160_jpeg(value_mpa: float | None, width: int = 1280, height: int = 720) -> bytes:
    """Генерирует тестовый JPEG-кадр прибора МТП-160 (либо перекрытый кадр при value_mpa=None)."""
    img = np.full((height, width, 3), (30, 34, 38), dtype=np.uint8)
    if value_mpa is None:
        # Имитация перекрытой рукой камеры: тёмный кадр без циферблата и стрелки
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        assert ok
        return buf.tobytes()

    cx, cy = width // 2, height // 2
    r_dial = 250
    cv2.circle(img, (cx, cy), r_dial + 22, (88, 94, 102), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r_dial, (244, 245, 242), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), r_dial, (55, 60, 65), 2, cv2.LINE_AA)

    def val_ang(v: float) -> float:
        return (135.0 + (v / 16.0) * 270.0) % 360.0

    for i in range(81):
        v = i * 0.2
        ang = math.radians(val_ang(v))
        c, s = math.cos(ang), math.sin(ang)
        r1 = r_dial - 14
        r0 = r_dial - (38 if i % 10 == 0 else 28 if i % 5 == 0 else 20)
        th = 3 if i % 10 == 0 else 2 if i % 5 == 0 else 1
        cv2.line(img, (int(cx + c * r0), int(cy + s * r0)), (int(cx + c * r1), int(cy + s * r1)), (30, 32, 35), th, cv2.LINE_AA)

    ang = math.radians(val_ang(value_mpa))
    c, s = math.cos(ang), math.sin(ang)
    nc, ns = -s, c
    tip = (cx + c * (r_dial - 26), cy + s * (r_dial - 26))
    tail = (cx - c * 42, cy - s * 42)
    pts = np.array([
        [tip[0], tip[1]],
        [cx + nc * 5.5, cy + ns * 5.5],
        [tail[0] + nc * 7.0, tail[1] + ns * 7.0],
        [tail[0] - nc * 7.0, tail[1] - ns * 7.0],
        [cx - nc * 5.5, cy - ns * 5.5],
    ], dtype=np.int32)
    cv2.fillConvexPoly(img, pts, (18, 20, 24), cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 13, (25, 28, 32), -1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
    assert ok
    return buf.tobytes()


def test_unit_thresholds_and_angles() -> None:
    # 1. Границы уставок, включая равенство порогу и отключённые нижние зоны
    thr_bi = {"ll_alert": 2.0, "l_warn": 4.0, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": True}
    assert vision.classify_level(2.0, thr_bi) == "alert"
    assert vision.classify_level(1.99, thr_bi) == "alert"
    assert vision.classify_level(2.01, thr_bi) == "warning"
    assert vision.classify_level(4.0, thr_bi) == "warning"
    assert vision.classify_level(4.01, thr_bi) == "normal"
    assert vision.classify_level(14.19, thr_bi) == "normal"
    assert vision.classify_level(14.2, thr_bi) == "warning"
    assert vision.classify_level(15.19, thr_bi) == "warning"
    assert vision.classify_level(15.2, thr_bi) == "alert"

    thr_uni = {**thr_bi, "lower_enabled": False}
    assert vision.classify_level(1.0, thr_uni) == "normal"
    assert vision.classify_level(3.0, thr_uni) == "normal"
    assert vision.classify_level(14.2, thr_uni) == "warning"
    assert vision.classify_level(15.2, thr_uni) == "alert"

    # 2. Переход через 0/360° и отсечка неверного направления CW/CCW
    cal_cw = {"v_min": 0.0, "theta_min": 135.0, "v_max": 16.0, "theta_max": 45.0, "direction": "cw"}
    v_before_zero = vision.angle_to_value(354.375, cal_cw)
    v_after_zero = vision.angle_to_value(23.0625, cal_cw)
    assert v_before_zero is not None and abs(v_before_zero - 13.0) < 0.02
    assert v_after_zero is not None and abs(v_after_zero - 14.7) < 0.02

    cal_wrong_ccw = {**cal_cw, "direction": "ccw"}
    # Стрелка на 12 часов (270°) лежит глубоко вне 90° дуги CCW -> None (недостоверно)
    assert vision.angle_to_value(270.0, cal_wrong_ccw) is None
    # Нулевой угловой размах -> None
    assert vision.angle_to_value(180.0, {**cal_cw, "theta_max": 135.0}) is None


def test_end_to_end_contracts() -> None:
    with TestClient(app) as client:
        # 0. Аутентификация (RBAC включён по умолчанию)
        r_auth = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": config.ADMIN_PASSWORD},
        )
        assert r_auth.status_code == 200, f"Не удалось авторизоваться: {r_auth.text}"

        # 1. Метаданные и 36 стабильных позиций
        meta = client.get("/api/meta").json()
        assert meta["demo_mode"] is True
        insts = client.get("/api/instruments").json()
        assert len(insts) == 36
        live_items = [x for x in insts if x["source_kind"] == "phone_cv"]
        sim_items = [x for x in insts if x["source_kind"] == "simulated"]
        assert len(live_items) == 1
        assert len(sim_items) == 35
        assert live_items[0]["id"] == "demo-mtp160-steam"
        assert live_items[0]["code"] == "К1-Р01"
        assert live_items[0]["quality"] == "disconnected"

        # 1b. Проверка 4 уставок (LL/L/H/HH) на всех 36 приборах (включая К1-Р01 и ТА2-Т02)
        for item in insts:
            th = item["thresholds"]
            assert th.get("lower_enabled") is not False, f"{item['code']}: lower_enabled disabled"
            for k in ("ll_alert", "l_warn", "h_warn", "hh_alert"):
                assert th.get(k) is not None, f"{item['code']}: missing threshold {k}"

        # 1c. Проверка многоузловых сценариев (mixed, peak, cascade): WARNING + CRITICAL + NO_DATA
        # одновременно по разным узлам (котёл, турбоагрегат/ТГ, деаэратор, теплосеть)
        sim_alerts = [x for x in sim_items if x["reading"]["level"] == "alert"]
        sim_warns = [x for x in sim_items if x["reading"]["level"] == "warning"]
        sim_stale = [x for x in sim_items if not x["reading"]["valid"]]
        assert len(sim_alerts) == 2
        assert len(sim_warns) == 3
        assert len(sim_stale) == 1
        mixed_groups = {x["group"] for x in (sim_alerts + sim_warns + sim_stale)}
        assert {"Котлоагрегаты", "Турбоагрегаты", "Питательный узел", "Теплосеть и насосная"}.issubset(mixed_groups)
        assert len(sim_alerts[0]["reading"]["sparkline"]) == 24
        assert sim_alerts[0]["reading"]["rate_per_min"] is not None

        # История любого симулируемого прибора доступна для вкладки «История» и CSV
        sim_hist = client.get("/api/instruments/sim-12/history?limit=30").json()
        assert len(sim_hist) == 30
        assert sim_hist[-1]["instrument_id"] == "ТА2-Т02"
        assert sim_hist[-1]["status_level"] == "alert"

        # Переключение пресетов симуляции через API
        sc_nom = client.post("/api/demo/scenario", json={"scenario": "nominal"}).json()
        assert sc_nom["scenario"] == "nominal"
        nom_insts = [x for x in client.get("/api/instruments").json() if x["source_kind"] == "simulated"]
        assert all(x["reading"]["level"] == "normal" and x["reading"]["valid"] for x in nom_insts)

        sc_peak = client.post("/api/demo/scenario", json={"scenario": "peak"}).json()
        assert sc_peak["scenario"] == "peak"
        peak_insts = [x for x in client.get("/api/instruments").json() if x["source_kind"] == "simulated"]
        peak_anom = [x for x in peak_insts if x["reading"]["level"] in ("alert", "warning") or not x["reading"]["valid"]]
        assert sum(1 for x in peak_insts if x["reading"]["level"] == "alert") == 2
        assert sum(1 for x in peak_insts if x["reading"]["level"] == "warning") == 4
        assert sum(1 for x in peak_insts if not x["reading"]["valid"]) == 1
        assert {"Котлоагрегаты", "Турбоагрегаты", "Питательный узел", "Теплосеть и насосная", "ГРУ и генераторы"}.issubset(
            {x["group"] for x in peak_anom}
        )

        sc_casc = client.post("/api/demo/scenario", json={"scenario": "cascade"}).json()
        assert sc_casc["scenario"] == "cascade"
        casc_insts = [x for x in client.get("/api/instruments").json() if x["source_kind"] == "simulated"]
        casc_anom = [x for x in casc_insts if x["reading"]["level"] in ("alert", "warning") or not x["reading"]["valid"]]
        assert sum(1 for x in casc_insts if x["reading"]["level"] == "alert") == 4
        assert sum(1 for x in casc_insts if x["reading"]["level"] == "warning") == 4
        assert sum(1 for x in casc_insts if not x["reading"]["valid"]) == 2
        assert {"Котлоагрегаты", "Турбоагрегаты", "Питательный узел", "Теплосеть и насосная", "ГРУ и генераторы"}.issubset(
            {x["group"] for x in casc_anom}
        )

        # Возвращаем смешанный режим перед основным прогоном камеры
        client.post("/api/demo/scenario", json={"scenario": "mixed"})

        # 2. Идемпотентная выдача QR и нераскрытие токена вне /api/phone/session
        qr1 = client.post("/api/phone/session", json={}).json()
        qr2 = client.post("/api/phone/session", json={"cam_id": "demo-mtp160-steam"}).json()
        assert qr1["cam_id"] == "demo-mtp160-steam"
        assert qr1["token"] == qr2["token"]
        assert qr2["regenerated"] is False
        assert len(client.get("/api/instruments").json()) == 36

        cams_dump = client.get("/api/cameras").text + client.get("/api/instruments").text
        assert qr1["token"] not in cams_dump

        # 3. Серверная валидация калибровки и уставок (равные границы, выход за шкалу, нулевая дуга)
        bad_eq = client.patch("/api/cameras/demo-mtp160-steam", json={
            "thresholds": {"h_warn": 14.5, "hh_alert": 14.5, "lower_enabled": False}
        })
        assert bad_eq.status_code == 422

        bad_range = client.patch("/api/cameras/demo-mtp160-steam", json={
            "thresholds": {"h_warn": 14.2, "hh_alert": 18.0, "lower_enabled": False}
        })
        assert bad_range.status_code == 422

        bad_span = client.patch("/api/cameras/demo-mtp160-steam", json={
            "calibration": {"v_min": 0.0, "theta_min": 135.0, "v_max": 16.0, "theta_max": 135.0, "direction": "cw"}
        })
        assert bad_span.status_code == 422

        # Защита основного демо-прибора от случайного удаления
        del_resp = client.delete("/api/cameras/demo-mtp160-steam")
        assert del_resp.status_code == 409

        # Подтверждение штатной настройки МТП-160
        ok_cfg = client.patch("/api/cameras/demo-mtp160-steam", json={
            "name": "Манометр острого пара К-1 (МТП-160)",
            "calibration": {"v_min": 0.0, "theta_min": 135.0, "v_max": 16.0, "theta_max": 45.0, "direction": "cw"},
            "thresholds": {"ll_alert": None, "l_warn": None, "h_warn": 14.2, "hh_alert": 15.2, "lower_enabled": False},
        })
        assert ok_cfg.status_code == 200

        # Начинаем чистый показ перед подачей кадров
        run_info = client.post("/api/demo/runs/start", json={"label": "Репетиция МТП-160"}).json()
        run_id = run_info["id"]

        # 4. Реальный поток кадров по WSS: 13.0 -> 14.7 -> 15.7 -> перекрытие -> 13.0
        token = qr1["token"]
        with client.websocket_connect(f"/ws/phone/demo-mtp160-steam?token={token}") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"

            def push_level(target_mpa: float | None, count: int = 12, pause: float = 0.36) -> dict:
                frame_bytes = render_mtp160_jpeg(target_mpa)
                last_ack = {}
                for _ in range(count):
                    ws.send_bytes(frame_bytes)
                    last_ack = ws.receive_json()
                    time.sleep(pause)
                return last_ack

            # Норма: 13.0 МПа
            ack_norm = push_level(13.0, count=6, pause=0.36)
            assert ack_norm["reading"]["valid"] is True
            assert ack_norm["reading"]["level"] == "normal"

            # Предупреждение: 14.7 МПа (EMA сходится к >14.2 за ~6-8 кадров)
            ack_warn = push_level(14.7, count=10, pause=0.36)
            assert ack_warn["reading"]["level"] == "warning"

            # Авария: 15.7 МПа (EMA сходится к >15.2)
            ack_alarm = push_level(15.7, count=11, pause=0.36)
            assert ack_alarm["reading"]["level"] == "alert"

            # Проверяем событие аварии камеры и адресное идемпотентное квитирование
            events = client.get("/api/events").json()
            alarm_evs = [
                e for e in events
                if e["kind"] == "alarm" and e["level"] == "alert" and e["cam_id"] == "demo-mtp160-steam"
            ]
            assert len(alarm_evs) >= 1
            alarm_ev_id = alarm_evs[0]["id"]
            assert alarm_evs[0]["acked"] is False
            assert alarm_evs[0]["has_frame"] is True

            ack1 = client.post(f"/api/events/{alarm_ev_id}/ack").json()
            assert ack1["ok"] is True and ack1["already_acked"] is False
            ack2 = client.post(f"/api/events/{alarm_ev_id}/ack").json()
            assert ack2["ok"] is True and ack2["already_acked"] is True

            # Зона прибора остаётся аварийной после квитирования
            cur_cam = client.get("/api/cameras/demo-mtp160-steam").json()
            assert cur_cam["reading"]["level"] == "alert"

            # Перекрываем камеру (невалидные кадры): тревога не сбрасывается как возврат в норму!
            ack_blind = push_level(None, count=4, pause=0.35)
            assert ack_blind["reading"]["valid"] is False
            assert ack_blind["reading"]["last_valid_level"] == "alert"

            # Возврат в норму: 13.0 МПа
            ack_ret = push_level(13.0, count=12, pause=0.36)
            assert ack_ret["reading"]["valid"] is True
            assert ack_ret["reading"]["level"] == "normal"

        # Проверяем запись возврата в норму и её связь с предыдущей аварией камеры
        events_after = client.get("/api/events").json()
        return_evs = [
            e for e in events_after
            if e["kind"] == "alarm" and e["level"] == "normal" and e["cam_id"] == "demo-mtp160-steam"
        ]
        assert len(return_evs) >= 1
        assert return_evs[0]["ref_event_id"] == alarm_ev_id
        assert return_evs[0]["ref_level"] == "alert"

        # 5. Завершаем показ и сверяем таблицу и CSV
        stopped_run = client.post("/api/demo/runs/stop", json={"run_id": run_id}).json()
        assert stopped_run["ended_at"] is not None

        run_data = client.get(f"/api/demo/runs/{run_id}/readings").json()
        assert run_data["count"] >= 4
        levels_recorded = {r["status_level"] for r in run_data["readings"]}
        assert {"normal", "warning", "alert"}.issubset(levels_recorded)
        assert all(r["source_kind"] == "phone_cv" for r in run_data["readings"])
        assert all(r["instrument_id"] == "К1-Р01" for r in run_data["readings"])

        csv_resp = client.get(f"/api/demo/runs/{run_id}/export.csv")
        assert csv_resp.status_code == 200
        csv_text = csv_resp.text.lstrip("\ufeff")
        csv_lines = [ln for ln in csv_text.strip().splitlines() if ln]
        assert csv_lines[0] == "timestamp_iso8601;instrument_id;source_kind;value;unit;raw_angle_deg;status_level"
        assert len(csv_lines) - 1 == run_data["count"]
        assert "simulated" not in csv_text

        # Старый маршрут экспорта без format=demo сохраняет прежний заголовок
        legacy_csv = client.get("/api/cameras/demo-mtp160-steam/export.csv").text.lstrip("\ufeff")
        assert legacy_csv.splitlines()[0] == "timestamp_iso8601;value_МПа;raw_angle_deg;status_level"

        # Повторный запуск показа создаёт пустой интервал, сохраняя прошлый
        next_run = client.post("/api/demo/runs/start", json={"label": "Показ №2"}).json()
        assert next_run["id"] != run_id
        next_data = client.get(f"/api/demo/runs/{next_run['id']}/readings").json()
        assert next_data["count"] == 0
        old_data = client.get(f"/api/demo/runs/{run_id}/readings").json()
        assert old_data["count"] == run_data["count"]


if __name__ == "__main__":
    test_unit_thresholds_and_angles()
    test_end_to_end_contracts()
    print("ALL DEMO DASHBOARD CONTRACT TESTS PASSED")
