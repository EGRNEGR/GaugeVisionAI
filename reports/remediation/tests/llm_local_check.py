"""
Проверка режима llm_enhanced генератора ТЗ на реальной локальной LLM (OpenAI-совместимый API:
Ollama / vLLM / llama.cpp server) — без облака и без mock-сервера.

  python reports/remediation/tests/llm_local_check.py --base-url http://127.0.0.1:11434/v1 \
      --model qwen3.5 --timeout 300 --out reports/remediation/evidence/llm

Проверяется: фактический ответ модели (engine_used = llm_enhanced), время ответа, язык,
отсутствие чисел, которых нет в исходных фактах (защита от выдуманных значений), сохранение
правового разграничения документа, безопасный откат при недоступности сервера.
Тексты сохраняются для экспертной оценки качества формулировок.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def numbers_in(text: str) -> set[str]:
    return {m.replace(",", ".").rstrip(".") for m in re.findall(r"\d+(?:[.,]\d+)?", text)}


def disp_item(iid: str, code: str, name: str, group: str, *, health: float, root: str, level: str, value: float,
              trips: int, rec: str, modernization: bool) -> dict:
    from app.dispatch_analyzer import ROOT_CAUSE_META

    return {
        "id": iid, "code": code, "short_name": name, "name": name, "group": group, "gauge_type": "pressure",
        "unit": "МПа", "decimals": 2, "source_kind": "simulated", "value": value, "level": level, "valid": True,
        "thresholds": {"h_warn": 14.2, "hh_alert": 15.2}, "calibration": {"v_min": 0, "v_max": 16},
        "health_score": health, "equipment_health": health, "instrument_health": 100.0, "optical_health": 95.0,
        "communication_health": 100.0, "root_cause": root, "root_cause_meta": ROOT_CAUSE_META[root],
        "recommendation": rec, "modernization_needed": modernization, "rate_symbol": "dP/dt",
        "rate_per_min": 0.4, "peak_rate_per_min": 1.2, "chatter_pct": 0.3, "overload_min": 14.5,
        "trips_shift": trips, "trips_24h": trips, "critical_wear": False,
    }


async def run(args: argparse.Namespace) -> dict:
    os.environ["GAUGEVISION_LLM_BASE_URL"] = args.base_url
    os.environ["GAUGEVISION_LLM_MODEL"] = args.model
    os.environ["GAUGEVISION_LLM_TIMEOUT"] = str(args.timeout)
    from app import config
    config.LLM_BASE_URL, config.LLM_MODEL, config.LLM_TIMEOUT_SECONDS = args.base_url, args.model, float(args.timeout)
    from app.spec_generator import LEGAL_DISCLAIMER, generate_spec_bundle

    ov = {"instruments": [
        disp_item("p1", "К1-Р01", "Манометр острого пара К-1", "Котлоагрегаты", health=41.0, root="process_anomaly",
                  level="alert", value=15.6, trips=4, rec="Превышение HH, проверка режима", modernization=True),
        disp_item("p2", "ТА2-Р01", "Манометр свежего пара Т-2", "Турбоагрегаты", health=96.0, root="nominal",
                  level="normal", value=12.9, trips=0, rec="Штатно", modernization=False),
        disp_item("p3", "Д6-Р01", "Деаэратор №1 давление", "Питательный узел", health=63.0, root="instrument_degradation",
                  level="normal", value=0.59, trips=1, rec="Дребезг стрелки, осмотр КИП", modernization=True),
    ]}
    det = await generate_spec_bundle(dispatch_overview=ov, events=[], snapshot_lookup={}, period="24h", mode="deterministic")
    t0 = time.perf_counter()
    llm = await generate_spec_bundle(dispatch_overview=ov, events=[], snapshot_lookup={}, period="24h", mode="llm_enhanced")
    llm_s = round(time.perf_counter() - t0, 1)
    base_nums = numbers_in(det["executive_summary"]) | numbers_in(det["markdown"])
    text = llm["executive_summary"]
    invented = sorted(n for n in numbers_in(text) - base_nums if n not in {"1", "2", "3", "4", "5", "12", "24", "102"})
    cyr = sum(1 for ch in text if "а" <= ch.lower() <= "я" or ch.lower() == "ё")
    letters = sum(1 for ch in text if ch.isalpha())

    # откат при недоступном сервере
    config.LLM_BASE_URL = "http://127.0.0.1:9/v1"
    t1 = time.perf_counter()
    fb = await generate_spec_bundle(dispatch_overview=ov, events=[], snapshot_lookup={}, period="24h", mode="llm_enhanced")
    fb_s = round(time.perf_counter() - t1, 2)
    res = {
        "base_url": args.base_url, "model": args.model, "timeout_s": args.timeout,
        "engine_used": llm["engine_used"], "llm_seconds": llm_s,
        "deterministic_summary": det["executive_summary"], "llm_summary": text,
        "llm_chars": len(text), "cyrillic_share": round(cyr / max(1, letters), 3),
        "think_tags_present": "<think>" in text.lower(),
        "numbers_not_in_source_facts": invented,
        "disclaimer_kept_in_document": LEGAL_DISCLAIMER in llm["markdown"],
        "economics_unchanged_by_llm": llm["economics"] == det["economics"],
        "fallback": {"engine_used": fb["engine_used"], "seconds": fb_s, "summary_is_deterministic": fb["executive_summary"] == det["executive_summary"]},
    }
    res["verdict"] = {
        "real_llm_answered": res["engine_used"].startswith("llm_enhanced"),
        "russian_text": res["cyrillic_share"] >= 0.8,
        "no_reasoning_leak": not res["think_tags_present"],
        "no_invented_numbers": not invented,
        "document_facts_untouched": res["disclaimer_kept_in_document"] and res["economics_unchanged_by_llm"],
        "fallback_safe": res["fallback"]["summary_is_deterministic"] and res["fallback"]["engine_used"].startswith("deterministic"),
    }
    res["passed"] = all(res["verdict"].values())
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--out", default=str(ROOT / "reports" / "remediation" / "evidence" / "llm"))
    args = ap.parse_args()
    res = asyncio.run(run(args))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm_local_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("engine_used", "llm_seconds", "verdict", "passed")}, ensure_ascii=False, indent=2))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
