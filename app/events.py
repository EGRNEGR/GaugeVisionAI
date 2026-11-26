"""
GaugeVision AI — журнал событий пульта.

Кольцевой буфер в памяти сервера, общий для всех открытых пультов:
  • alarm — переход прибора между зонами уставок (норма / предупреждение /
    авария) со стоп-кадром распознавания в момент срабатывания;
  • link  — смена статуса видеопотока (в сети / переподключение / офлайн);
  • ack   — квитирование оператором;
  • config — изменение калибровки, уставок или источника прибора.

Журнал живёт до перезапуска сервера; архив показаний остаётся в SQLite.
"""
from __future__ import annotations

import itertools
import threading
from collections import OrderedDict, deque
from typing import Any

from . import config
from .db import utcnow_iso
from .vision import _num

EVENT_KINDS = ("alarm", "link", "ack", "config")
_LEVEL_RANK = {"normal": 0, "warning": 1, "alert": 2}


def crossed_setpoint(value: float | None, thresholds: dict[str, Any]) -> str | None:
    """Какая уставка нарушена: LL / L / H / HH (как в classify_level)."""
    if value is None:
        return None
    ll = _num(thresholds.get("ll_alert"))
    lw = _num(thresholds.get("l_warn"))
    hw = _num(thresholds.get("h_warn"))
    hh = _num(thresholds.get("hh_alert"))
    if ll is not None and value <= ll:
        return "LL"
    if hh is not None and value >= hh:
        return "HH"
    if lw is not None and value <= lw:
        return "L"
    if hw is not None and value >= hw:
        return "H"
    return None


class EventLog:
    """Последние EVENTS_MAX событий и стоп-кадры к последним EVENT_SNAPSHOTS_MAX из них."""

    def __init__(self, max_events: int = config.EVENTS_MAX,
                 max_snapshots: int = config.EVENT_SNAPSHOTS_MAX) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._snaps: OrderedDict[int, bytes] = OrderedDict()
        self._max_snaps = max_snapshots
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def add(self, kind: str, *, cam_id: str | None = None, cam_name: str | None = None,
            level: str | None = None, prev_level: str | None = None,
            value: float | None = None, unit: str | None = None,
            setpoint: str | None = None, setpoint_value: float | None = None,
            text: str = "", snapshot: bytes | None = None) -> dict[str, Any]:
        if kind not in EVENT_KINDS:
            raise ValueError(f"неизвестный тип события: {kind}")
        with self._lock:
            ev_id = next(self._ids)
            # срабатывание требует квитирования; возврат в норму и служебные события — нет
            needs_ack = kind == "alarm" and _LEVEL_RANK.get(level or "normal", 0) > \
                _LEVEL_RANK.get(prev_level or "normal", 0)
            ev = {
                "id": ev_id, "ts": utcnow_iso(), "kind": kind,
                "cam_id": cam_id, "cam_name": cam_name,
                "level": level, "prev_level": prev_level,
                "value": value, "unit": unit,
                "setpoint": setpoint, "setpoint_value": setpoint_value,
                "text": text, "has_frame": snapshot is not None,
                "acked": not needs_ack, "acked_ts": None, "acked_by": None,
            }
            self._events.append(ev)
            if snapshot is not None:
                self._snaps[ev_id] = snapshot
                while len(self._snaps) > self._max_snaps:
                    old_id, _ = self._snaps.popitem(last=False)
                    self._mark_no_frame(old_id)
            return dict(ev)

    def _mark_no_frame(self, ev_id: int) -> None:
        for ev in self._events:
            if ev["id"] == ev_id:
                ev["has_frame"] = False
                return

    def acknowledge(self, ts: str, by: str) -> list[int]:
        """Квитирует все неквитированные срабатывания; возвращает их id."""
        done = []
        with self._lock:
            for ev in self._events:
                if not ev["acked"]:
                    ev["acked"], ev["acked_ts"], ev["acked_by"] = True, ts, by
                    done.append(ev["id"])
        return done

    def forget_camera(self, cam_id: str) -> None:
        """Удалённый прибор: стоп-кадры освобождаются, записи журнала остаются."""
        with self._lock:
            for ev in self._events:
                if ev["cam_id"] == cam_id and ev["id"] in self._snaps:
                    del self._snaps[ev["id"]]
                    ev["has_frame"] = False

    def list(self, limit: int = 300, cam_id: str | None = None) -> list[dict[str, Any]]:
        """Последние события, новые первыми."""
        with self._lock:
            out = []
            for ev in reversed(self._events):
                if cam_id and ev["cam_id"] != cam_id:
                    continue
                out.append(dict(ev))
                if len(out) >= limit:
                    break
            return out

    def snapshot(self, ev_id: int) -> bytes | None:
        with self._lock:
            return self._snaps.get(ev_id)
