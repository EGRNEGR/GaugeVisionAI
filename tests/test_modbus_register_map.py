"""
Регрессионные и функциональные тесты карты регистров Modbus TCP (v1 + v2).

Проверяют:
  1. Полную обратную совместимость базовых адресов 0..799 и 900..905 (v1).
  2. Новые системные регистры v2: heartbeat (906, переполнение 65535 -> 0),
     last_sync_unix uint32 (907..908), register_map_version=2 (909),
     extended_base=2000 (910), extended_stride=8 (911).
  3. Расширенный блок приборов 2000 + idx*8: reading_age_s (насыщение 0..65535),
     confidence_x1000, битовые флаги state_flags, last_valid_unix, last_valid_value.
  4. Режим «зависания» без обрыва TCP (set_sync_frozen): heartbeat перестаёт расти,
     TCP остаётся открытым и отвечает на FC 0x03/0x04.
  5. Коды исключений Modbus TCP: 0x0B (чужой unit_id), 0x02 (выход за MAX_REGISTERS = 5208),
     0x03 (недопустимый count), 0x01 (запись FC 0x06 / 0x10 запрещена).
  6. Поведение при GAUGEVISION_MODBUS_ENABLED=0 (сервер не стартует).

Запуск:
  CUDA_VISIBLE_DEVICES="" GAUGEVISION_DEVICE=cpu python -B tests/test_modbus_register_map.py
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import math
import os
import socket
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

from app import config
from app.scada_gateway import (
    FLAG_ALARM_ACTIVE,
    FLAG_CALIBRATION_SET,
    FLAG_CAMERA_ONLINE,
    FLAG_CONFIDENCE_AVAIL,
    FLAG_DIAL_DETECTED,
    FLAG_IS_SIMULATED,
    FLAG_READING_STALE,
    FLAG_READING_VALID,
    ModbusTcpGateway,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _modbus_exchange(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    tx_id: int,
    unit_id: int,
    pdu: bytes,
) -> tuple[int, int, bytes]:
    mbap = struct.pack(">HHHB", tx_id, 0, len(pdu) + 1, unit_id)
    writer.write(mbap + pdu)
    await writer.drain()
    hdr = await asyncio.wait_for(reader.readexactly(7), timeout=2.0)
    rx_tx, proto, length, rx_unit = struct.unpack(">HHHB", hdr)
    assert rx_tx == tx_id and proto == 0, f"Неверный MBAP: {hdr.hex()}"
    resp_pdu = await asyncio.wait_for(reader.readexactly(length - 1), timeout=2.0)
    return rx_tx, rx_unit, resp_pdu


async def _read_regs(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    tx_id: int,
    unit_id: int,
    start: int,
    count: int,
    fc: int = 3,
) -> list[int]:
    _, rx_unit, resp = await _modbus_exchange(
        reader, writer, tx_id, unit_id, struct.pack(">BHH", fc, start, count)
    )
    assert rx_unit == unit_id
    assert resp[0] == fc, f"Неожиданное исключение Modbus: {resp.hex()}"
    assert resp[1] == count * 2
    return list(struct.unpack(f">{count}H", resp[2:]))


def _sample_instruments(now_unix: int) -> list[dict]:
    ts_now = _dt.datetime.fromtimestamp(now_unix - 2, tz=_dt.timezone.utc).isoformat()
    ts_old = _dt.datetime.fromtimestamp(now_unix - 120, tz=_dt.timezone.utc).isoformat()
    return [
        # idx 0: живая камера CV в норме
        {
            "id": "live-01",
            "code": "К1-Р01",
            "short_name": "Острый пар К-1",
            "unit": "МПа",
            "status": "online",
            "source_kind": "phone_cv",
            "calibration": {"v_min": 0.0, "v_max": 16.0},
            "reading": {
                "valid": True,
                "value": 13.75,
                "level": "normal",
                "confidence": 0.912,
                "dial_detected": True,
                "ts": ts_now,
                "last_valid_ts": ts_now,
                "age_s": 2.0,
            },
        },
        # idx 1: симулируемый канал в CRITICAL
        {
            "id": "sim-02",
            "code": "К1-Т01",
            "short_name": "Перегретый пар",
            "unit": "°C",
            "status": "online",
            "source_kind": "simulated",
            "calibration": {"v_min": 0.0, "v_max": 600.0},
            "reading": {
                "valid": True,
                "value": 570.25,
                "level": "alert",
                "confidence": None,
                "ts": ts_now,
                "last_valid_ts": ts_now,
            },
        },
        # idx 2: устаревший канал STALE с сохранённым last_valid_value и большим возрастом
        {
            "id": "sim-30",
            "code": "ДС1-Р01",
            "short_name": "Тяга ДС-1",
            "unit": "кПа",
            "status": "offline",
            "source_kind": "simulated",
            "calibration": {"v_min": -5.0, "v_max": 5.0},
            "reading": {
                "valid": False,
                "value": None,
                "last_valid_value": -2.18,
                "level": "stale",
                "confidence": None,
                "ts": ts_old,
                "last_valid_ts": ts_old,
                "age_s": 90000.0,  # проверка насыщения uint16 -> 65535
            },
        },
        # idx 3: камера без единого достоверного показания и без калибровки
        {
            "id": "cam-never",
            "code": "КМ-04",
            "short_name": "Новая камера",
            "unit": "МПа",
            "status": "offline",
            "source_kind": "camera_cv",
            "calibration": {},
            "reading": {
                "valid": False,
                "value": None,
                "level": "stale",
            },
        },
    ]


def test_v1_backward_compat_and_v2_extended_map() -> None:
    async def _run() -> None:
        orig = (config.MODBUS_ENABLED, config.MODBUS_HOST, config.MODBUS_PORT, config.MODBUS_UNIT_ID)
        port = _free_port()
        config.MODBUS_ENABLED = True
        config.MODBUS_HOST = "127.0.0.1"
        config.MODBUS_PORT = port
        config.MODBUS_UNIT_ID = 1

        now_u = 1_764_228_000
        mb = ModbusTcpGateway()
        insts = _sample_instruments(now_u)
        mb.update_from_instruments(
            insts,
            health_by_id={"live-01": 98.4, "sim-02": 41.2, "sim-30": 65.0, "cam-never": 12.5},
            sf_pending=7,
            outage_active=True,
            now_unix=float(now_u),
        )
        await mb.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                # 1. Регрессия v1: базовый блок 0..15 (4 прибора * 4 регистра)
                base_regs = await _read_regs(reader, writer, 1, 1, 0, 16, fc=3)
                # idx 0: 13.75, OK (0), health 984
                v0 = struct.unpack(">f", struct.pack(">HH", base_regs[0], base_regs[1]))[0]
                assert abs(v0 - 13.75) < 1e-4
                assert base_regs[2] == 0 and base_regs[3] == 984
                # idx 1: 570.25, CRITICAL (2), health 412
                v1 = struct.unpack(">f", struct.pack(">HH", base_regs[4], base_regs[5]))[0]
                assert abs(v1 - 570.25) < 1e-3
                assert base_regs[6] == 2 and base_regs[7] == 412
                # idx 2: STALE -> quiet NaN 0x7FC00000, status 3, health 650
                assert (base_regs[8], base_regs[9]) == (0x7FC0, 0x0000)
                assert math.isnan(struct.unpack(">f", struct.pack(">HH", base_regs[8], base_regs[9]))[0])
                assert base_regs[10] == 3 and base_regs[11] == 650

                # FC 0x04 (Input Registers) отдаёт те же значения
                base_fc4 = await _read_regs(reader, writer, 2, 1, 0, 8, fc=4)
                assert base_fc4 == base_regs[:8]

                # 2. Системный блок 900..911 (v1: 900..905 + v2: 906..911)
                sys_regs = await _read_regs(reader, writer, 3, 1, 900, 12, fc=3)
                assert sys_regs[0] == 4   # total
                assert sys_regs[1] == 1   # critical
                assert sys_regs[2] == 0   # warning
                assert sys_regs[3] == 2   # stale
                assert sys_regs[4] == 7   # sf_pending
                assert sys_regs[5] == 1   # outage_flag
                assert sys_regs[6] == 1   # heartbeat (1-я синхронизация)
                sync_unix = (sys_regs[7] << 16) | sys_regs[8]
                assert sync_unix == now_u
                assert sys_regs[9] == 2     # register_map_version
                assert sys_regs[10] == 2000 # extended_base
                assert sys_regs[11] == 8    # extended_stride

                # 3. Расширенный блок приборов 2000..2031 (4 * 8 регистров)
                ext_regs = await _read_regs(reader, writer, 4, 1, 2000, 32, fc=3)
                # idx 0 (live-01): age=2, conf=912, flags, last_valid_unix=now_u-2, last_valid_value=13.75
                assert ext_regs[0] == 2
                assert ext_regs[1] == 912
                expected_f0 = (
                    FLAG_CAMERA_ONLINE | FLAG_DIAL_DETECTED | FLAG_READING_VALID
                    | FLAG_CALIBRATION_SET | FLAG_CONFIDENCE_AVAIL
                )
                assert ext_regs[2] == expected_f0, f"flags idx0: {ext_regs[2]:#x} != {expected_f0:#x}"
                assert ((ext_regs[3] << 16) | ext_regs[4]) == now_u - 2
                lv0 = struct.unpack(">f", struct.pack(">HH", ext_regs[5], ext_regs[6]))[0]
                assert abs(lv0 - 13.75) < 1e-4
                assert ext_regs[7] == 0

                # idx 1 (sim-02): simulated + alarm_active, confidence_avail=0
                f1 = ext_regs[8 + 2]
                assert (f1 & FLAG_IS_SIMULATED) != 0
                assert (f1 & FLAG_ALARM_ACTIVE) != 0
                assert (f1 & FLAG_CONFIDENCE_AVAIL) == 0
                assert ext_regs[8 + 1] == 0

                # idx 2 (sim-30): age saturated 65535, STALE flag, last_valid_value=-2.18
                assert ext_regs[16 + 0] == 65535
                f2 = ext_regs[16 + 2]
                assert (f2 & FLAG_READING_STALE) != 0 and (f2 & FLAG_READING_VALID) == 0
                assert (f2 & FLAG_CAMERA_ONLINE) == 0 and (f2 & FLAG_IS_SIMULATED) != 0
                assert ((ext_regs[16 + 3] << 16) | ext_regs[16 + 4]) == now_u - 120
                lv2 = struct.unpack(">f", struct.pack(">HH", ext_regs[16 + 5], ext_regs[16 + 6]))[0]
                assert abs(lv2 - (-2.18)) < 1e-3

                # idx 3 (cam-never): age=65535, flags only STALE, last_valid_unix=0, last_valid_value=NaN
                assert ext_regs[24 + 0] == 65535
                assert ext_regs[24 + 2] == FLAG_READING_STALE
                assert ((ext_regs[24 + 3] << 16) | ext_regs[24 + 4]) == 0
                assert (ext_regs[24 + 5], ext_regs[24 + 6]) == (0x7FC0, 0x0000)

                # 4. Переполнение heartbeat 65535 -> 0
                mb._heartbeat = 65535
                mb.update_from_instruments(insts, now_unix=float(now_u + 2))
                hb_wrapped = await _read_regs(reader, writer, 5, 1, 906, 1)
                assert hb_wrapped == [0], f"Ожидалось переполнение 65535 -> 0, получено {hb_wrapped}"
                mb.update_from_instruments(insts, now_unix=float(now_u + 4))
                hb_next = await _read_regs(reader, writer, 6, 1, 906, 1)
                assert hb_next == [1]

                # 5. Зависание синхронизации без обрыва TCP
                mb.set_sync_frozen(True)
                mb.update_from_instruments(insts, now_unix=float(now_u + 60))
                hb_frozen = await _read_regs(reader, writer, 7, 1, 906, 3)
                assert hb_frozen[0] == 1, "В режиме freeze heartbeat не должен расти"
                assert ((hb_frozen[1] << 16) | hb_frozen[2]) == now_u + 4
                mb.set_sync_frozen(False)
                mb.update_from_instruments(insts, now_unix=float(now_u + 62))
                hb_resumed = await _read_regs(reader, writer, 8, 1, 906, 1)
                assert hb_resumed == [2]

                # 6. Исключения Modbus:
                # 6a. Граница карты (MAX_REGISTERS = 5208 после продления прогнозного блока на слоты 61..199):
                # последний адрес читается, MAX_REGISTERS -> 0x02, запрос через границу -> 0x02
                last = ModbusTcpGateway.MAX_REGISTERS - 1
                ok_last = await _read_regs(reader, writer, 9, 1, last, 1)
                assert len(ok_last) == 1
                _, _, exc_oob1 = await _modbus_exchange(reader, writer, 10, 1,
                                                        struct.pack(">BHH", 3, ModbusTcpGateway.MAX_REGISTERS, 1))
                assert exc_oob1 == bytes([0x83, 0x02]), f"Ожидалось 0x02, получено {exc_oob1.hex()}"
                _, _, exc_oob2 = await _modbus_exchange(reader, writer, 11, 1, struct.pack(">BHH", 3, last, 2))
                assert exc_oob2 == bytes([0x83, 0x02])
                # прежняя граница v2 (4095/4096) теперь внутри карты: адреса 0..4095 не сдвинулись
                assert len(await _read_regs(reader, writer, 14, 1, 4095, 2)) == 2

                # 6b. Недопустимое число регистров (0 и 126) -> 0x03
                _, _, exc_cnt0 = await _modbus_exchange(reader, writer, 12, 1, struct.pack(">BHH", 3, 0, 0))
                assert exc_cnt0 == bytes([0x83, 0x03])
                _, _, exc_cnt126 = await _modbus_exchange(reader, writer, 13, 1, struct.pack(">BHH", 3, 0, 126))
                assert exc_cnt126 == bytes([0x83, 0x03])

                # 6c. Чужой unit_id=2 -> 0x0B
                _, rx_u, exc_uid = await _modbus_exchange(reader, writer, 14, 2, struct.pack(">BHH", 3, 0, 4))
                assert rx_u == 2 and exc_uid == bytes([0x83, 0x0B])

                # 6d. Запрет записи (FC 0x06 Write Single Register и FC 0x10 Write Multiple) -> 0x01
                _, _, exc_w6 = await _modbus_exchange(reader, writer, 15, 1, struct.pack(">BHH", 6, 0, 123))
                assert exc_w6 == bytes([0x86, 0x01])
                _, _, exc_w16 = await _modbus_exchange(reader, writer, 16, 1, struct.pack(">BHHBH", 16, 0, 1, 2, 123))
                assert exc_w16 == bytes([0x90, 0x01])

                # 7. Проверка registers_snapshot() обратной совместимости и новых полей
                snap = mb.registers_snapshot(limit=4)
                assert snap["system"]["HR40901_instruments_total"] == 4
                assert snap["system"]["HR40907_heartbeat"] == 2
                assert snap["system"]["HR40910_register_map_version"] == 2
                assert snap["system"]["HR40911_extended_base"] == 2000
                assert snap["system"]["HR40912_extended_stride"] == 8
                assert snap["instruments"][0]["hr_value"] == 40001
                assert snap["instruments"][0]["hr_ext_base"] == 42001
                assert snap["instruments"][0]["confidence_x1000"] == 912
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await mb.stop()
            config.MODBUS_ENABLED, config.MODBUS_HOST, config.MODBUS_PORT, config.MODBUS_UNIT_ID = orig

    asyncio.run(_run())


def test_modbus_disabled_does_not_bind() -> None:
    async def _run() -> None:
        orig_en = config.MODBUS_ENABLED
        config.MODBUS_ENABLED = False
        mb = ModbusTcpGateway()
        try:
            await mb.start()
            st = mb.status()
            assert st["enabled"] is False and st["listening"] is False
        finally:
            await mb.stop()
            config.MODBUS_ENABLED = orig_en

    asyncio.run(_run())


def main() -> None:
    tests = [
        test_v1_backward_compat_and_v2_extended_map,
        test_modbus_disabled_does_not_bind,
    ]
    for fn in tests:
        fn()
        print(f"[PASS] {fn.__name__}")
    print(f"ALL MODBUS REGISTER MAP TESTS PASSED ({len(tests)}/{len(tests)})")


if __name__ == "__main__":
    main()
