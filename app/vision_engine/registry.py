"""
GaugeVision AI 3.1 — Реестр локальных моделей (ModelRegistry).

Обеспечивает:
  • проверку целостности весов по SHA-256 до загрузки;
  • защиту от path traversal (загрузка только из MODELS_DIR);
  • полностью автономную работу без обращений в интернет;
  • метаданные архитектуры, лицензии, версии, формата и совместимых бэкендов.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config

logger = logging.getLogger("gaugevision.vision_engine.registry")


@dataclass(frozen=True)
class ModelRecord:
    model_id: str
    architecture: str
    task: str                  # "detect" | "needle_keypoint" | "needle_seg" | "pose"
    version: str
    filename: str
    format: str                # "pt" | "onnx"
    sha256: str
    input_size: int
    classes: list[str]
    license: str
    backends: list[str]
    trained_date: str = ""
    data_sources: str = ""
    notes: str = ""

    def resolved_path(self, models_dir: Path | None = None) -> Path:
        base = (models_dir or config.MODELS_DIR).resolve()
        candidate = (base / self.filename).resolve()
        if not candidate.is_relative_to(base):
            raise ValueError(f"Недопустимый путь модели вне MODELS_DIR: {self.filename}")
        return candidate


class ModelRegistry:
    """Потокобезопасный реестр весов моделей с проверкой SHA-256."""

    def __init__(self, models_dir: Path | None = None, manifest_path: Path | None = None) -> None:
        self.models_dir = (models_dir or config.MODELS_DIR).resolve()
        self.manifest_path = manifest_path or (self.models_dir / "registry.json")
        self._lock = threading.Lock()
        self._records: dict[str, ModelRecord] = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self._records.clear()
            if not self.manifest_path.is_file():
                return
            try:
                raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                for item in raw.get("models", []):
                    rec = ModelRecord(
                        model_id=str(item["model_id"]),
                        architecture=str(item["architecture"]),
                        task=str(item["task"]),
                        version=str(item["version"]),
                        filename=str(item["filename"]),
                        format=str(item["format"]),
                        sha256=str(item.get("sha256", "")).lower(),
                        input_size=int(item.get("input_size", 640)),
                        classes=list(item.get("classes", [])),
                        license=str(item.get("license", "unknown")),
                        backends=list(item.get("backends", ["pytorch"])),
                        trained_date=str(item.get("trained_date", "")),
                        data_sources=str(item.get("data_sources", "")),
                        notes=str(item.get("notes", "")),
                    )
                    self._records[rec.model_id] = rec
            except Exception as exc:
                logger.warning("Не удалось загрузить реестр моделей %s: %s", self.manifest_path, exc)

    def list_models(self) -> list[dict[str, Any]]:
        with self._lock:
            out = []
            for rec in self._records.values():
                p = rec.resolved_path(self.models_dir)
                exists = p.is_file()
                out.append({
                    "model_id": rec.model_id,
                    "architecture": rec.architecture,
                    "task": rec.task,
                    "version": rec.version,
                    "filename": rec.filename,
                    "format": rec.format,
                    "sha256": rec.sha256,
                    "input_size": rec.input_size,
                    "classes": rec.classes,
                    "license": rec.license,
                    "backends": rec.backends,
                    "trained_date": rec.trained_date,
                    "available": exists,
                    "size_bytes": p.stat().st_size if exists else 0,
                })
            return out

    def get(self, model_id: str) -> ModelRecord | None:
        with self._lock:
            return self._records.get(model_id)

    def verify_and_resolve(self, model_id: str) -> tuple[Path | None, str | None]:
        """Возвращает (path, error_reason). При несовпадении SHA-256 возвращает (None, reason)."""
        rec = self.get(model_id)
        if rec is None:
            return None, f"model_not_registered:{model_id}"
        try:
            p = rec.resolved_path(self.models_dir)
        except ValueError as exc:
            return None, f"unsafe_model_path:{exc}"
        if not p.is_file():
            return None, f"model_file_missing:{rec.filename}"
        if not rec.sha256 or len(rec.sha256) != 64:
            logger.error("Отсутствует или некорректен SHA-256 в реестре для модели %s", rec.model_id)
            return None, f"model_sha256_missing:{rec.model_id}"
        actual = hashlib.sha256(p.read_bytes()).hexdigest().lower()
        if actual != rec.sha256:
            logger.error("Нарушена целостность весов %s: ожидался SHA-256 %s, получен %s",
                         rec.filename, rec.sha256[:12], actual[:12])
            return None, f"model_sha256_mismatch:{rec.model_id}"
        return p, None


_REGISTRY: ModelRegistry | None = None
_REG_LOCK = threading.Lock()


def get_registry() -> ModelRegistry:
    global _REGISTRY
    with _REG_LOCK:
        if _REGISTRY is None:
            _REGISTRY = ModelRegistry()
        return _REGISTRY
