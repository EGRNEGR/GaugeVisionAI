"""
GaugeVision AI — Multi-Gauge в сервисе мониторинга (смешивается в GaugeService).

Источник (cameras) с одним основным прибором обрабатывается прежним конвейером GaugePipeline —
поведение однокамерной конфигурации не меняется. Как только у источника появляется хотя бы один
дополнительный прибор, кадры источника обрабатывает MultiGaugeProcessor: один проход детектора,
трекер по якорным ROI, свой конвейер на каждый прибор (SHARED_DATA_CONTRACT § 1–5).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import cv2
import numpy as np
from fastapi import HTTPException

from . import config, db, demo, multigauge, vision
from .stream_manager import encode_jpeg

logger = logging.getLogger("gaugevision.multigauge")

_SCALE_KEYS = ("v_min", "v_max", "theta_min", "theta_max", "direction", "points")
_DEFAULT_SHAPE = (720, 1280)


class MultiGaugeServiceMixin:
    """Логические приборы источников. Ожидает атрибуты GaugeService: cameras, pipelines, last,
    streams, broker, hub, executor, store_forward, emit(), _on_reading(), _spawn_io()."""

    instruments: dict[str, dict[str, Any]]
    mg: dict[str, multigauge.MultiGaugeProcessor]

    # -- состояние -----------------------------------------------------------
    def _mg_reset(self) -> None:
        self.instruments = {}
        self.mg = {}
        self._mg_track_state: dict[str, str | None] = {}
        self._mg_last_telemetry: dict[str, float] = {}
        self._mg_frame_shape: dict[str, tuple[int, int]] = {}

    async def _mg_load(self) -> None:
        self.instruments = {i["id"]: i for i in await db.list_instruments()}

    async def _mg_reload_source(self, source_id: str) -> None:
        for iid in [i for i, v in self.instruments.items() if v["source_id"] == source_id]:
            self.instruments.pop(iid, None)
        for inst in await db.list_instruments(source_id):
            self.instruments[inst["id"]] = inst

    def _mg_forget_source(self, source_id: str) -> None:
        for iid in [i for i, v in self.instruments.items() if v["source_id"] == source_id]:
            self.instruments.pop(iid, None)
            self.last.pop(iid, None)
            self._mg_track_state.pop(iid, None)
            self._mg_last_telemetry.pop(iid, None)
        self.mg.pop(source_id, None)

    def secondary_instruments(self, source_id: str) -> list[dict[str, Any]]:
        return sorted((i for i in self.instruments.values() if i["source_id"] == source_id and not i["is_primary"]),
                      key=lambda i: i["created_at"])

    def is_multi(self, source_id: str) -> bool:
        return any(i["enabled"] for i in self.secondary_instruments(source_id))

    def instrument_view(self, inst: dict[str, Any]) -> dict[str, Any]:
        """Прибор в форме, которую понимают конвейер, _on_reading и пульт (как запись камеры)."""
        src = self.cameras.get(inst["source_id"]) or {}
        if inst["is_primary"]:
            # для основного прибора шкала, уставки и имя ведутся в записи камеры (старый API)
            base = {k: v for k, v in src.items() if k != "source_url"}
        else:
            base = {"name": inst["name"], "gauge_type": inst["gauge_type"], "unit": inst["unit"],
                    "calibration": inst["calibration"], "thresholds": inst["thresholds"],
                    "created_at": inst["created_at"]}
        return {
            **base, "id": inst["id"], "type": src.get("type", "rtsp"),
            "source_id": inst["source_id"], "instrument_id": inst["id"], "is_primary": inst["is_primary"],
            "code": inst.get("code"), "tag": inst.get("tag"), "roi": inst.get("roi") or {},
            "calibration_rev": int(inst.get("calibration_rev") or 0),
            "calibration_meta": inst.get("calibration_meta") or {},
            "modbus_slot": inst.get("modbus_slot"), "enabled": inst["enabled"],
        }

    def multi_views(self, source_id: str) -> list[dict[str, Any]]:
        views = []
        prim = self.instruments.get(source_id)
        if prim is not None:
            views.append(self.instrument_view(prim))
        views.extend(self.instrument_view(i) for i in self.secondary_instruments(source_id) if i["enabled"])
        return views

    def mg_processor(self, source_id: str) -> multigauge.MultiGaugeProcessor:
        mp = self.mg.get(source_id)
        if mp is None:
            mp = self.mg[source_id] = multigauge.MultiGaugeProcessor(source_id)
        return mp

    # -- обработка кадра источника ------------------------------------------
    @staticmethod
    def _run_multi(mp: multigauge.MultiGaugeProcessor, frame: np.ndarray, views: list[dict[str, Any]]
                   ) -> tuple[multigauge.MultiGaugeResult, bytes | None, dict[str, bytes]]:
        res = mp.process(frame, views, with_overlay=True)
        jpeg = None
        if res.overlay is not None:
            ov = res.overlay
            h, w = ov.shape[:2]
            if w > config.PREVIEW_MAX_WIDTH:
                k = config.PREVIEW_MAX_WIDTH / float(w)
                ov = cv2.resize(ov, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
            jpeg = encode_jpeg(ov, 78)
            res.overlay = None
        snaps: dict[str, bytes] = {}
        for iid, r in res.readings.items():
            if r.snapshot is not None:
                snaps[iid] = encode_jpeg(r.snapshot, config.SNAPSHOT_JPEG_QUALITY) or b""
                r.snapshot = None
        return res, jpeg, snaps

    def _mg_after_frame(self, source_id: str, views: list[dict[str, Any]], res: multigauge.MultiGaugeResult,
                        snaps: dict[str, bytes], adaptive: Any, degraded: bool) -> None:
        self._mg_frame_shape[source_id] = res.frame_shape
        per_inst: dict[str, tuple[float | None, float, str | None]] = {}
        for v in views:
            r = res.readings.get(v["id"])
            if r is None:
                continue
            cal = v.get("calibration") or {}
            span = abs(float(cal.get("v_max", 10.0)) - float(cal.get("v_min", 0.0))) or 1.0
            per_inst[v["id"]] = (r.ema_value if r.valid else None, span, r.status_level if r.valid else None)
        adaptive.update_multi(per_inst, degraded=degraded, process_ms=res.total_ms)
        for v in views:
            r = res.readings.get(v["id"])
            if r is None:
                continue
            self._on_reading(v["id"], v, r, snaps.get(v["id"]) or None, source_id=source_id)
            self._mg_track_event(v, r)
        self._mg_publish_telemetry(views)

    def _mg_track_event(self, view: dict[str, Any], r: vision.GaugeReading) -> None:
        state = (r.debug.get("track") or {}).get("state")
        prev = self._mg_track_state.get(view["id"])
        self._mg_track_state[view["id"]] = state
        bad = ("lost", "ambiguous")
        common = {"cam_id": view["id"], "cam_name": view.get("name"), "instrument_id": view["id"],
                  "source_id": view["source_id"]}
        if state in bad and prev not in bad:
            self.emit("instrument", level="warning",
                      text="track_lost" if state == "lost" else "track_ambiguous", **common)
        elif prev in bad and state not in bad and state is not None:
            self.emit("instrument", level="normal", text="reacquired", **common)

    def _mg_publish_telemetry(self, views: list[dict[str, Any]]) -> None:
        """Телеметрия каждого прибора многоприборного источника в MQTT через Store-and-Forward (§ 3.3)."""
        now = time.monotonic()
        for v in views:
            st = self.last.get(v["id"])
            if not st or not st.get("valid") or st.get("value") is None:
                continue
            if now - self._mg_last_telemetry.get(v["id"], 0.0) < config.MG_TELEMETRY_INTERVAL:
                continue
            self._mg_last_telemetry[v["id"]] = now
            try:
                self._spawn_io(self.store_forward.enqueue(
                    channel_id=v["id"], payload_type="telemetry",
                    severity=st.get("level") if st.get("level") in ("warning", "alert") else "info",
                    payload={
                        "schema": "gv.telemetry/1", "instrument_id": v["id"], "source_id": v["source_id"],
                        "code": v.get("code") or v.get("name"), "ts": st.get("ts"), "value": st.get("value"),
                        "unit": v.get("unit"), "level": st.get("level"), "valid": True,
                        "confidence": st.get("confidence"), "calibration_rev": v.get("calibration_rev", 0),
                    },
                ))
            except RuntimeError:
                return

    # -- публичная модель ----------------------------------------------------
    def instrument_fields(self, inst_id: str) -> dict[str, Any]:
        """Поля контракта § 5.1 для записи прибора на пульте и в /api/instruments."""
        inst = self.instruments.get(inst_id)
        if inst is None:
            return {"instrument_id": inst_id, "source_id": inst_id, "camera_id": inst_id, "gauge_slot": 0,
                    "is_primary": True}
        return {
            "instrument_id": inst_id, "source_id": inst["source_id"], "camera_id": inst["source_id"],
            "gauge_slot": int(inst.get("gauge_slot") or 0), "is_primary": inst["is_primary"],
            "modbus_slot": inst.get("modbus_slot"), "calibration_rev": int(inst.get("calibration_rev") or 0),
            "calibration_meta": inst.get("calibration_meta") or {}, "anchor_roi": inst.get("roi") or {},
            "tag": inst.get("tag"), "multi_gauge": self.is_multi(inst["source_id"]),
        }

    def public_instrument(self, inst: dict[str, Any], grid_pos: int) -> dict[str, Any]:
        view = self.instrument_view(inst)
        source_id = inst["source_id"]
        st_info = self.streams.info(source_id)
        rd = self.last.get(inst["id"])
        if rd is not None:
            rd = {**rd, **demo.compute_live_states(view, st_info, rd)}
        raw = {**view, "status": self.streams.status_of(source_id), "stream": st_info, "reading": rd,
               "source_url": None}
        out = demo.unify_camera(raw, grid_pos=grid_pos, is_primary_demo=False)
        src = self.cameras.get(source_id) or {}
        out.update(self.instrument_fields(inst["id"]))
        out["camera_id"] = source_id
        out["code"] = inst.get("code") or out["code"]
        out["group"] = src.get("name") or out.get("group")
        return out

    def public_source_instruments(self, source_id: str) -> list[dict[str, Any]]:
        return [x for x in self.public_instruments() if x.get("source_id") == source_id]

    # -- регистрация приборов ------------------------------------------------
    def _source_shape(self, source_id: str) -> tuple[int, int]:
        return self._mg_frame_shape.get(source_id) or _DEFAULT_SHAPE

    async def mg_detect(self, source_id: str) -> dict[str, Any]:
        """Кандидаты циферблатов на текущем кадре источника с пометкой уже зарегистрированных."""
        if source_id not in self.cameras:
            raise HTTPException(404, "Источник не найден")
        frame, _ = self.broker.latest_frame(source_id)
        if frame is None:
            raise HTTPException(409, "С источника ещё не получено ни одного кадра")
        h, w = frame.shape[:2]
        if w > config.MAX_PROCESS_WIDTH:
            k = config.MAX_PROCESS_WIDTH / float(w)
            frame = cv2.resize(frame, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
        loop = asyncio.get_running_loop()
        dets, info = await loop.run_in_executor(self.executor, multigauge.detect_dials_multi, frame)
        shape = frame.shape[:2]
        self._mg_frame_shape[source_id] = (shape[0], shape[1])
        cands = [{"index": k, "source": d.source, "score": round(float(d.score), 3),
                  "anchor": multigauge.roi_to_anchor(d, shape)} for k, d in enumerate(dets)]
        registered = [self.instrument_view(i) for i in self.instruments.values() if i["source_id"] == source_id]
        registered = [v for v in registered if v["roi"]]
        primary_anchor = self._primary_anchor_guess(source_id, shape)
        marked = multigauge.match_candidates(cands, registered, shape)
        for c in marked:
            c["is_primary_dial"] = bool(primary_anchor and multigauge.anchor_overlap(
                c["anchor"], primary_anchor, shape) < config.MG_REGISTER_OVERLAP)
        return {"source_id": source_id, "frame": {"w": int(shape[1]), "h": int(shape[0])},
                "detect": info, "candidates": marked, "limit": config.MG_MAX_INSTRUMENTS_PER_SOURCE}

    def _primary_anchor_guess(self, source_id: str, shape: tuple[int, int]) -> dict[str, Any] | None:
        """Якорь основного прибора: сохранённый, иначе ROI, которую ведёт однокамерный конвейер."""
        prim = self.instruments.get(source_id)
        if prim and prim.get("roi") and {"cx", "cy", "r"} <= set(prim["roi"]):
            return prim["roi"]
        pipe = self.pipelines.get(source_id)
        roi = getattr(pipe, "roi", None)
        if roi is not None and roi.source != "frame":
            # ROI конвейера — в координатах обработанного кадра той же формы
            return multigauge.roi_to_anchor(roi, shape)
        return None

    def _check_duplicate(self, source_id: str, anchor: dict[str, Any], skip_id: str | None = None) -> None:
        shape = self._source_shape(source_id)
        for inst in self.instruments.values():
            if inst["source_id"] != source_id or inst["id"] == skip_id:
                continue
            other = inst.get("roi") or {}
            if {"cx", "cy", "r"} <= set(other) and \
                    multigauge.anchor_overlap(anchor, other, shape) < config.MG_REGISTER_OVERLAP:
                raise HTTPException(409, f"Этот циферблат уже зарегистрирован как прибор «{inst['name']}»")

    async def mg_add_instrument(self, source_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if source_id not in self.cameras:
            raise HTTPException(404, "Источник не найден")
        on_source = [i for i in self.instruments.values() if i["source_id"] == source_id]
        if len(on_source) >= config.MG_MAX_INSTRUMENTS_PER_SOURCE:
            raise HTTPException(409, f"На одном источнике не больше {config.MG_MAX_INSTRUMENTS_PER_SOURCE} приборов")
        anchor = dict(data["roi"])
        shape = self._source_shape(source_id)
        prim = self.instruments.get(source_id)
        if prim is not None and not (prim.get("roi") and {"cx", "cy", "r"} <= set(prim["roi"])):
            # первый дополнительный прибор: основной должен получить свой якорь, иначе его не отличить
            guess = self._primary_anchor_guess(source_id, shape)
            if guess is None:
                raise HTTPException(409, "Сначала укажите на кадре циферблат основного прибора источника")
            if multigauge.anchor_overlap(anchor, guess, shape) < config.MG_REGISTER_OVERLAP:
                raise HTTPException(409, "Этот циферблат — основной прибор источника; выберите другой")
            await db.update_instrument(source_id, {"roi": guess})
        self._check_duplicate(source_id, anchor)
        inst = await db.create_instrument(
            source_id=source_id, name=data["name"], roi=anchor, gauge_type=data.get("gauge_type") or "pressure",
            unit=data.get("unit"), code=data.get("code"), tag=data.get("tag"),
            calibration=data.get("calibration"), thresholds=data.get("thresholds"),
            calibration_meta=data.get("calibration_meta"),
        )
        await self._mg_reload_source(source_id)
        self.cameras[source_id] = await db.get_camera(source_id) or self.cameras[source_id]
        self.mg_processor(source_id).request_redetect()
        out = self.public_instrument(self.instruments[inst["id"]], grid_pos=len(self.public_instruments()))
        self.hub.broadcast({"type": "instrument_added", "instrument": out})
        self.emit("instrument", cam_id=inst["id"], cam_name=inst["name"], instrument_id=inst["id"],
                  source_id=source_id, text="added")
        return out

    async def mg_update_instrument(self, inst_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Изменение дополнительного прибора или якоря/обозначений основного (шкала основного —
        через update_camera, см. API)."""
        inst = self.instruments.get(inst_id)
        if inst is None:
            raise HTTPException(404, "Прибор не найден")
        source_id = inst["source_id"]
        if "roi" in patch and patch["roi"]:
            self._check_duplicate(source_id, patch["roi"], skip_id=inst_id)
        old_view = self.instrument_view(inst)
        updated = await db.update_instrument(inst_id, patch)
        if updated is None:
            raise HTTPException(404, "Прибор не найден")
        self.instruments[inst_id] = updated
        if inst["is_primary"]:
            self.cameras[source_id] = await db.get_camera(source_id) or self.cameras[source_id]
        new_view = self.instrument_view(updated)
        mp = self.mg.get(source_id)
        scale_changed = any(old_view["calibration"].get(k) != new_view["calibration"].get(k) for k in _SCALE_KEYS)
        unit_changed = old_view.get("unit") != new_view.get("unit")
        if mp is not None and inst_id in mp.pipelines and (scale_changed or unit_changed or "roi" in patch):
            mp.pipelines[inst_id].reset()
            if "roi" in patch:
                mp.request_redetect()
        prev_last = self.last.get(inst_id)
        if prev_last and (scale_changed or unit_changed):
            prev_last.update(value=None, raw_value=None, valid=False, level=None, awaiting_post_cal=True)
        elif prev_last and "thresholds" in patch and prev_last.get("valid") and prev_last.get("value") is not None:
            new_lv = vision.classify_level(prev_last["value"], new_view["thresholds"])
            prev_lv = prev_last.get("last_valid_level") or "normal"
            prev_last["level"] = prev_last["last_valid_level"] = new_lv
            if new_lv != prev_lv:
                self.emit("alarm", cam_id=inst_id, cam_name=new_view["name"], instrument_id=inst_id,
                          source_id=source_id, level=new_lv, prev_level=prev_lv, value=prev_last["value"],
                          unit=new_view["unit"])
        out = next((x for x in self.public_instruments() if x["id"] == inst_id), None) or {}
        self.hub.broadcast({"type": "instrument_updated", "instrument": out})
        changed = [k for k in patch if patch[k] != inst.get(k)]
        if changed:
            self.emit("config", cam_id=inst_id, cam_name=new_view["name"], instrument_id=inst_id,
                      source_id=source_id, text=",".join(sorted(changed)))
        return out

    async def mg_delete_instrument(self, inst_id: str) -> None:
        inst = self.instruments.get(inst_id)
        if inst is None:
            raise HTTPException(404, "Прибор не найден")
        if inst["is_primary"]:
            raise HTTPException(409, "Основной прибор удаляется только вместе с источником")
        self._db_buffer = [r for r in self._db_buffer if not (len(r) > 7 and r[7] == inst_id)]
        if not await db.delete_instrument(inst_id):
            raise HTTPException(404, "Прибор не найден")
        self.instruments.pop(inst_id, None)
        self.last.pop(inst_id, None)
        self._mg_track_state.pop(inst_id, None)
        self._mg_last_telemetry.pop(inst_id, None)
        self.events.forget_camera(inst_id)
        if not self.is_multi(inst["source_id"]):
            # снова один прибор: источник возвращается к однокамерному конвейеру
            self.mg.pop(inst["source_id"], None)
            pipe = self.pipelines.get(inst["source_id"])
            if pipe is not None:
                pipe.reset(keep_roi=True)
        self.hub.broadcast({"type": "instrument_deleted", "instrument_id": inst_id})
        self.emit("instrument", cam_id=inst_id, cam_name=inst["name"], instrument_id=inst_id,
                  source_id=inst["source_id"], text="removed")
