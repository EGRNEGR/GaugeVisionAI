"""
Сторонний клиент Modbus TCP (pymodbus) для проверки регистровой карты GaugeVision AI.

  <tools_py> modbus_probe.py --port 15620 --unit 1 --start 0 --count 16
Печатает одну строку JSON: сырые регистры, декодированные float32 (big-endian,
по 4 регистра на прибор) либо код исключения Modbus.
"""
from __future__ import annotations

import argparse
import json
import math
import struct

from pymodbus.client import ModbusTcpClient


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--unit", type=int, default=1)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=16)
    ap.add_argument("--fc", type=int, default=3, choices=(3, 4))
    args = ap.parse_args()
    cl = ModbusTcpClient("127.0.0.1", port=args.port, timeout=3)
    if not cl.connect():
        print(json.dumps({"connected": False}))
        return
    try:
        fn = cl.read_holding_registers if args.fc == 3 else cl.read_input_registers
        rr = fn(args.start, count=args.count, device_id=args.unit)
        if rr.isError():
            print(json.dumps({"connected": True, "error": True,
                              "exception_code": getattr(rr, "exception_code", None), "repr": str(rr)}))
            return
        regs = list(rr.registers)
        instruments = []
        for i in range(0, len(regs) - 3, 4):
            val = struct.unpack(">f", struct.pack(">HH", regs[i], regs[i + 1]))[0]
            instruments.append({
                "index": (args.start + i) // 4,
                "value": None if math.isnan(val) else round(val, 4),
                "is_nan": math.isnan(val),
                "status": regs[i + 2],
                "health_x10": regs[i + 3],
            })
        print(json.dumps({"connected": True, "error": False, "registers": regs, "instruments": instruments}))
    finally:
        cl.close()


if __name__ == "__main__":
    main()
