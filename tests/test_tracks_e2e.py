"""
Сквозные интеграционные тесты Трека №2 (Архитектурная видеоаналитика,
Adaptive FPS, Store-and-Forward SQLite WAL, MQTT/Modbus TCP) и Трека №1
(Умная диспетчеризация, Health Score, автогенерация ТЗ и .docx).
"""
from __future__ import annotations

import asyncio
import io
import os
import struct
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Изолированные временные БД и принудительный CPU-режим до импорта app
_TMP_DIR = Path(tempfile.mkdtemp(prefix="gv_tracks_e2e_"))
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"
os.environ["GAUGEVISION_DEMO"] = "1"
os.environ["GAUGEVISION_DB"] = str(_TMP_DIR / "demo.db")
os.environ["GAUGEVISION_SF_DB"] = str(_TMP_DIR / "sf_wal.db")
os.environ["GAUGEVISION_MODBUS_ENABLED"] = "1"
os.environ["GAUGEVISION_MODBUS_PORT"] = "15502"

from fastapi.testclient import TestClient  # noqa: E402
from app import main as app_main  # noqa: E402


async def _probe_modbus_tcp(port: int) -> tuple[int, ...]:
    """Реальный wire-level запрос Modbus TCP FC 0x03 (Read Holding Registers)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        # Transaction=1, Proto=0, Len=6, Unit=1, FC=3, StartAddr=900 (HR 40901), Count=6
        req = struct.pack(">HHHBBHH", 1, 0, 6, 1, 3, 900, 6)
        writer.write(req)
        await writer.drain()
        mbap = await asyncio.wait_for(reader.readexactly(7), timeout=2.0)
        tx, proto, length, unit = struct.unpack(">HHHB", mbap)
        assert tx == 1 and proto == 0 and unit == 1
        pdu = await asyncio.wait_for(reader.readexactly(length - 1), timeout=2.0)
        fc, byte_cnt = pdu[0], pdu[1]
        assert fc == 3 and byte_cnt == 12
        return struct.unpack(">6H", pdu[2:14])
    finally:
        writer.close()
        await writer.wait_closed()


def run_tests() -> None:
    with TestClient(app_main.app) as client:
        # Аутентификация (RBAC включён по умолчанию)
        r_auth = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": app_main.config.ADMIN_PASSWORD},
        )
        assert r_auth.status_code == 200, f"Не удалось авторизоваться: {r_auth.text}"

        # 1. Базовая совместимость: 36 приборов на месте
        r = client.get("/api/instruments")
        assert r.status_code == 200
        instruments = r.json()
        assert len(instruments) == 36, f"Ожидалось 36 приборов, получено {len(instruments)}"

        # Даём стендовым Edge-видеопотокам обработать первые кадры
        time.sleep(2.4)

        # 2. Трек №2: Архитектура, Edge-воркеры, Adaptive FPS, качество видеосигнала
        r = client.get("/api/architecture/status")
        assert r.status_code == 200
        arch = r.json()
        assert arch["edge_node"]["channels_total"] >= 3
        bench_streams = [s for s in arch["streams"] if s["is_bench"]]
        assert len(bench_streams) >= 2, "Стендовые видеоканалы Edge должны быть активны"
        b0 = bench_streams[0]
        assert b0["frames_total"] > 0, "Стендовый канал должен генерировать реальные кадры OpenCV"
        assert b0["health_status"] in ("ONLINE", "DEGRADED")

        # Проверка реального JPEG-кадра стендового потока с CV-разметкой
        rf = client.get(f"/api/architecture/streams/{b0['id']}/frame.jpg?overlay=1")
        assert rf.status_code == 200 and rf.content.startswith(b"\xff\xd8")

        # 3. Симуляция деградации видеосигнала (пар/дым -> DEGRADED, обрыв -> OFFLINE, восстановление -> ONLINE)
        rd = client.post("/api/architecture/degrade", json={"stream_id": b0["id"], "mode": "steam"})
        assert rd.status_code == 200 and rd.json()["injected_fault"] == "steam"
        time.sleep(1.2)
        st_after_steam = next(s for s in client.get("/api/architecture/streams").json() if s["id"] == b0["id"])
        assert st_after_steam["health_status"] == "DEGRADED", f"Ожидался DEGRADED при паре: {st_after_steam['quality']}"
        assert st_after_steam["quality"]["steam_occlusion"] is True

        rd_off = client.post("/api/architecture/degrade", json={"stream_id": b0["id"], "mode": "offline"})
        assert rd_off.status_code == 200
        time.sleep(0.5)
        st_after_off = next(s for s in client.get("/api/architecture/streams").json() if s["id"] == b0["id"])
        assert st_after_off["health_status"] == "OFFLINE"

        rd_rec = client.post("/api/architecture/degrade", json={"stream_id": b0["id"], "mode": "recover"})
        assert rd_rec.status_code == 200 and rd_rec.json()["injected_fault"] is None

        # 4. Store-and-Forward: контролируемый обрыв связи -> буферизация в SQLite WAL -> восстановление и досылка пачками
        ro_on = client.post("/api/architecture/outage", json={"active": True, "reason": "Тест обрыва АСУ ТП"})
        assert ro_on.status_code == 200
        assert ro_on.json()["store_forward"]["outage_active"] is True
        time.sleep(4.5)  # цикл _architecture_sync_loop пишет каждые 2 с
        sf_mid = client.get("/api/architecture/store-forward").json()
        assert sf_mid["sync_state"] == "BUFFERING"
        assert sf_mid["pending_count"] >= 2, f"Ожидалось накопление очереди при обрыве, получено {sf_mid}"
        assert sf_mid["wal_mode"] is True

        ro_off = client.post("/api/architecture/outage", json={"active": False, "reason": "Восстановление"})
        assert ro_off.status_code == 200
        rf_flush = client.post("/api/architecture/store-forward/flush")
        assert rf_flush.status_code == 200
        sf_end = client.get("/api/architecture/store-forward").json()
        assert sf_end["pending_count"] == 0, f"Очередь должна очиститься после восстановления: {sf_end}"
        assert sf_end["delivered_total"] > 0
        assert len(sf_end["recent_batches"]) >= 1

        # 5. SCADA: MQTT сообщения и Modbus TCP регистры (REST + реальный TCP-сокет FC 0x03)
        mqtt_res = client.get("/api/scada/mqtt/messages").json()
        assert mqtt_res["status"]["published_total"] > 0
        assert len(mqtt_res["messages"]) > 0

        mb_res = client.get("/api/scada/modbus/registers").json()
        assert mb_res["system"]["HR40901_instruments_total"] == 36
        assert len(mb_res["instruments"]) == 36

        regs = asyncio.run(_probe_modbus_tcp(15502))
        assert regs[0] == 36, f"Modbus TCP HR40901 должен вернуть 36 приборов, получено {regs}"

        # 6. Трек №1: Умная диспетчеризация (Health Score, производная dV/dt, дребезг, первопричины)
        disp = client.get("/api/dispatch/overview").json()
        assert disp["summary"]["total"] == 36
        assert 0.0 < disp["summary"]["avg_health_score"] <= 100.0
        assert len(disp["recommendations"]) >= 4
        by_c = disp["summary"]["by_root_cause"]
        assert by_c["process_anomaly"] >= 1, f"Должны быть тех. перегрузки: {by_c}"
        assert (by_c["instrument_degradation"] + by_c["optical_degradation"]) >= 1

        det = client.get("/api/dispatch/instrument/sim-02").json()
        assert det["code"] == "К1-Т01"
        assert len(det["rate_series"]) >= 2
        ev_img = client.get("/api/dispatch/evidence/sim-02/frame.jpg")
        assert ev_img.status_code == 200 and ev_img.content.startswith(b"\xff\xd8")

        incs = client.get("/api/dispatch/incidents").json()
        assert len(incs) >= 4

        # 7. Автогенерация предпросмотра (.md) и полноценного .docx со встроенными кадрами
        spec_req = {
            "period": "24h",
            "group": "all",
            "instrument_id": "all",
            "mode": "deterministic",
            "format": "docx",
            "plant_name": "ТЭЦ-22 ПАО «Интер РАО»",
            "doc_number": "ТЗ-КИП-TEST-001",
        }
        prev = client.post("/api/specs/preview", json=spec_req).json()
        md = prev["markdown"]
        for expected_sec in (
            "## 1. Паспорт обследуемого технологического узла",
            "## 2. Сводный протокол инструментального видеомониторинга",
            "## 3. Дефектная ведомость",
            "## 4. Техническое задание на модернизацию",
            "## 5. Технико-экономическое обоснование",
        ):
            assert expected_sec in md, f"В Markdown отсутствует раздел: {expected_sec}"
        assert prev["economics"]["capex_rub"] > 0
        assert prev["economics"]["payback_months"] >= 1

        doc_resp = client.post("/api/specs/generate", json=spec_req)
        assert doc_resp.status_code == 200
        assert "wordprocessingml.document" in doc_resp.headers["content-type"]
        docx_bytes = doc_resp.content
        assert len(docx_bytes) > 15_000, f"Слишком маленький .docx ({len(docx_bytes)} байт)"

        # Сохраняем тестовый .docx для проверки
        out_docx = _TMP_DIR / "TZ_KIP_TEST_001.docx"
        out_docx.write_bytes(docx_bytes)

        # Строгая валидация OpenXML-архива, XML-парсинга и встроенных доказательных изображений
        with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as zf:
            names = set(zf.namelist())
            for req_part in ("[Content_Types].xml", "_rels/.rels", "word/document.xml",
                             "word/styles.xml", "word/header1.xml", "word/footer1.xml",
                             "word/_rels/document.xml.rels"):
                assert req_part in names, f"Отсутствует часть OpenXML: {req_part}"
            doc_xml = zf.read("word/document.xml")
            root = ET.fromstring(doc_xml)
            all_text = "".join(root.itertext())
            assert "ТЗ-КИП-TEST-001" in all_text
            assert "Метран-" in all_text
            assert "Простой срок окупаемости" in all_text
            media_imgs = [n for n in names if n.startswith("word/media/image")]
            assert len(media_imgs) >= 2, f"В .docx должны быть встроены доказательные кадры, найдено {media_imgs}"
            for img_name in media_imgs:
                assert zf.read(img_name).startswith(b"\xff\xd8"), f"Некорректный JPEG внутри .docx: {img_name}"

        print(
            f"ALL TRACK 1 & TRACK 2 E2E TESTS PASSED "
            f"(docx={len(docx_bytes)} bytes, media_imgs={len(media_imgs)}, "
            f"sf_batches={len(sf_end['recent_batches'])}, modbus_hr40901={regs[0]})"
        )


if __name__ == "__main__":
    run_tests()
