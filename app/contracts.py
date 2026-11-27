"""
GaugeVision AI — унифицированные контракты идентификации приборов и инженерных паспортов.

Обеспечивает совместимость между текущей одноприборной моделью (1 камера = 1 прибор)
и будущей многоприборной архитектурой Multi-Gauge Vision (1 камера = N приборов
с собственными `instrument_id` и `gauge_slot`), а также стендовыми каналами.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class InstrumentIdentity:
    """Стабильный ключ прибора для SQLite, Predictive Analytics, Optimizer и SCADA."""

    instrument_id: str
    camera_id: str | None
    gauge_slot: int | None
    code: str
    name: str
    short_name: str
    group: str
    gauge_type: str
    unit: str
    source_kind: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_instrument_identity(inst: dict[str, Any]) -> InstrumentIdentity:
    """
    Извлекает унифицированную идентификацию прибора из записи `public_instruments()`,
    `dispatch_overview`, `cameras` или будущего multi-gauge объекта.

    Правила:
      • `instrument_id` — первичный стабильный идентификатор прибора (для multi-gauge
        может иметь вид `<camera_id>#g<slot>` или отдельный UUID, отличный от `camera_id`).
      • `camera_id` — идентификатор физической камеры (`None` для симуляции).
      • `gauge_slot` — 0-based номер циферблата в кадре камеры (`0` по умолчанию для
        одноприборных камер, `int` для multi-gauge, `None` для симуляции).
    """
    raw_id = str(inst.get("instrument_id") or inst.get("id") or "").strip()
    source_kind = str(inst.get("source_kind") or ("simulated" if inst.get("type") == "simulated" else "camera_cv"))

    raw_cam_id = inst.get("camera_id")
    if raw_cam_id is None and source_kind != "simulated":
        # Совместимость с текущей моделью (id == camera_id) и форматом `<cam_id>#g<slot>`
        raw_cam_id = raw_id.split("#", 1)[0] if "#" in raw_id else (raw_id or None)
    camera_id = str(raw_cam_id).strip() if raw_cam_id else None

    raw_slot = inst.get("gauge_slot")
    gauge_slot: int | None = None
    if raw_slot is not None:
        try:
            gauge_slot = max(0, int(raw_slot))
        except (TypeError, ValueError):
            gauge_slot = None
    elif source_kind != "simulated" and camera_id is not None:
        if "#g" in raw_id:
            tail = raw_id.rsplit("#g", 1)[-1]
            gauge_slot = int(tail) if tail.isdigit() else 0
        else:
            gauge_slot = 0

    code = str(inst.get("code") or raw_id).strip()
    name = str(inst.get("name") or inst.get("short_name") or code).strip()
    short_name = str(inst.get("short_name") or name).strip()
    group = str(inst.get("group") or "Общие").strip()
    gauge_type = str(inst.get("gauge_type") or "pressure").strip()
    unit = str(inst.get("unit") or "").strip()

    return InstrumentIdentity(
        instrument_id=raw_id,
        camera_id=camera_id,
        gauge_slot=gauge_slot,
        code=code,
        name=name,
        short_name=short_name,
        group=group,
        gauge_type=gauge_type,
        unit=unit,
        source_kind=source_kind,
    )


def default_passport_for_instrument(inst: dict[str, Any]) -> dict[str, Any]:
    """
    Вычисляет детерминированный инженерный паспорт прибора по его технологическому контуру.
    Не придумывает фиктивных аварий — использует только реальный цех, тип прибора и уставки.
    """
    ident = resolve_instrument_identity(inst)
    grp_l = ident.group.lower()
    name_l = f"{ident.name} {ident.short_name}".lower()

    is_hazardous = any(k in grp_l or k in name_l for k in ("топлив", "газ", "мазут"))

    # Категория критичности технологического контура ТЭЦ (I / II / III)
    if is_hazardous or any(k in grp_l for k in ("котло", "турбо")) or any(
        k in name_l for k in ("острого пара", "барабан", "подшипн", "масла смазки", "свежего пара")
    ):
        crit_class = 1
        crit_weight = 1.55
    elif any(k in grp_l for k in ("питательн", "гру", "генератор")) or ident.gauge_type in ("pressure", "temperature", "level"):
        crit_class = 2
        crit_weight = 1.15
    else:
        crit_class = 3
        crit_weight = 0.85

    # Межповерочный интервал и базовая дата очередной поверки (ориентировочно, редактируется инженером)
    due_date = (_dt.date.today() + _dt.timedelta(days=180 if crit_class == 1 else 365)).isoformat()

    return {
        "instrument_id": ident.instrument_id,
        "camera_id": ident.camera_id,
        "gauge_slot": ident.gauge_slot,
        "code": ident.code,
        "name": ident.name,
        "group_name": ident.group,
        "gauge_type": ident.gauge_type,
        "unit": ident.unit,
        "criticality_class": crit_class,
        "criticality_weight": crit_weight,
        "hazardous_zone": is_hazardous,
        "mandatory_regulation": False,
        "install_year": None,
        "verification_due_date": due_date,
        "custom_capex_rub": None,
        "custom_downtime_risk_rub_yr": None,
        "notes": "",
    }
