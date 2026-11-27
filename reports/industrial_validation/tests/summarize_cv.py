"""
Метрики CV-валидации по результатам eval_cv_pipeline.py.

  python summarize_cv.py --runs <dir> --label baseline [--meterfl <dir>] [--out summary.json]

Определения (все доли — от числа снимков в наборе, если не сказано иное):
  det_rate         — циферблат локализован верно: не запасной frame_roi, центр в пределах 0,25 радиуса
                     шкалы от эталонного, размер эллипса 0,7–2,2 радиуса шкалы;
  valid_rate       — конвейер выдал достоверное показание; refusal_rate = 1 − valid_rate;
  err_norm         — |V − эталон| / (Vmax − Vmin) для валидных показаний; для интервального эталона —
                     расстояние до интервала (0, если внутри);
  gross_rate       — доля валидных показаний с err_norm > 10 % шкалы (дополнительно — от всех снимков);
  in_interval_rate — для интервального эталона: валидное показание внутри интервала.
Причина каждой грубой ошибки: localization (неверный ROI) → needle (ошибка угла стрелки > 10°, где
известен эталонный угол) → scale_model (ошибка оракула > 5 %: двухточечная линейная модель шкалы
не описывает прибор) → other.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TARGETS = {
    "det_rate": (">=", 0.95), "valid_rate": (">=", 0.90), "mean_err_norm": ("<=", 0.02),
    "p95_err_norm": ("<=", 0.05), "gross_rate_valid": ("<=", 0.01),
}


def pct(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def cause(r: dict[str, Any]) -> str:
    if r.get("det_ok") is False:
        return "localization"
    if r.get("angle_err") is not None and r["angle_err"] > 10:
        return "needle"
    if r.get("oracle_err_norm") is not None and r["oracle_err_norm"] > 0.05:
        return "scale_model"
    return "other"


def stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in rows if "error" not in r]
    n = len(rows)
    if not n:
        return {"n": 0}
    det = [r for r in rows if r.get("det_ok") is not None]
    valid = [r for r in rows if r.get("valid")]
    errs = [r["err_norm"] for r in valid if r.get("err_norm") is not None]
    gross = [r for r in valid if (r.get("err_norm") or 0) > 0.10]
    iv = [r for r in rows if r.get("gt_kind") == "interval"]
    ivv = [r for r in iv if r.get("valid")]
    out = {
        "n": n,
        "det_rate": len([r for r in det if r["det_ok"]]) / len(det) if det else None,
        "valid_rate": len(valid) / n,
        "refusal_rate": 1 - len(valid) / n,
        "n_valid_scored": len(errs),
        "mean_err_norm": sum(errs) / len(errs) if errs else None,
        "rmse_norm": math.sqrt(sum(e * e for e in errs) / len(errs)) if errs else None,
        "median_err_norm": pct(errs, 0.5),
        "p95_err_norm": pct(errs, 0.95),
        "max_err_norm": max(errs) if errs else None,
        "gross_rate_valid": len(gross) / len(valid) if valid else None,
        "gross_rate_all": len(gross) / n,
        "within_2pct_all": len([e for e in errs if e <= 0.02]) / n,
        "within_5pct_all": len([e for e in errs if e <= 0.05]) / n,
        "in_interval_rate_valid": (len([r for r in ivv if r.get("in_interval")]) / len(ivv)) if ivv else None,
        "in_interval_rate_all": (len([r for r in ivv if r.get("in_interval")]) / len(iv)) if iv else None,
        "refusal_reasons": dict(Counter(r.get("invalid_reason") for r in rows if not r.get("valid"))),
        "gross_causes": dict(Counter(cause(r) for r in gross)),
        "median_process_ms": pct([r["process_ms"] for r in rows if r.get("process_ms")], 0.5),
    }
    ang = [r["angle_err"] for r in valid if r.get("angle_err") is not None]
    if ang:
        out["median_angle_err_deg"] = pct(ang, 0.5)
        out["p95_angle_err_deg"] = pct(ang, 0.95)
    orc = [r["oracle_err_norm"] for r in rows if r.get("oracle_err_norm") is not None]
    if orc:
        out["oracle_median_err_norm"] = pct(orc, 0.5)
        out["oracle_p95_err_norm"] = pct(orc, 0.95)
    return out


def physical(rows: list[dict[str, Any]], units: dict[str, str]) -> dict[str, Any]:
    """MAE/RMSE в единицах шкалы — только внутри групп с одинаковой единицей и точечным эталоном."""
    g = defaultdict(list)
    for r in rows:
        if r.get("valid") and r.get("gt_kind") == "point" and r.get("err_abs") is not None:
            g[(units.get(r["file"]) or "?", r.get("span"))].append(r["err_abs"])
    out = {}
    for (u, span), e in sorted(g.items(), key=lambda kv: -len(kv[1])):
        if len(e) < 5:
            continue
        out[f"{u}, шкала {span:g}"] = {"n": len(e), "mae": sum(e) / len(e), "rmse": math.sqrt(sum(x * x for x in e) / len(e)),
                                       "median": pct(e, 0.5), "p95": pct(e, 0.95), "max": max(e)}
    return out


def targets_check(s: dict[str, Any]) -> dict[str, Any]:
    res = {}
    for k, (op, thr) in TARGETS.items():
        v = s.get(k)
        res[k] = {"value": v, "target": f"{op} {thr}", "met": (v is not None and (v >= thr if op == ">=" else v <= thr))}
    return res


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--meterfl")
    ap.add_argument("--out")
    args = ap.parse_args()
    runs = Path(args.runs)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    units = {r["file"]: r.get("unit") for r in manifest["items"]}
    attrs = {}
    if args.meterfl:
        p = Path(args.meterfl) / "data" / "metadata" / "client_assignment.jsonl"
        for line in p.read_text(encoding="utf-8").splitlines():
            a = json.loads(line)
            attrs[a["file"]] = a
    summary: dict[str, Any] = {"label": args.label, "sets": {}}
    for sub in ("primary", "arc", "final", "dev"):
        p = runs / f"{args.label}_{sub}.jsonl"
        if not p.is_file():
            continue
        rows = load(p)
        s = {"overall": stats(rows), "targets": None, "by_model": {}, "by_gt_type": {}, "by_dataset": {},
             "by_condition": {}, "by_tag": {}, "physical_units": physical(rows, units)}
        s["targets"] = targets_check(s["overall"])
        for key, field in (("by_model", "model"), ("by_gt_type", "gt_type"), ("by_dataset", "dataset")):
            grp = defaultdict(list)
            for r in rows:
                grp[r.get(field)].append(r)
            s[key] = {str(k): stats(v) for k, v in sorted(grp.items(), key=lambda kv: str(kv[0]))}
        cond = defaultdict(list)
        for r in rows:
            a = attrs.get(r["file"])
            if a:
                cond[f"viewpoint={a.get('viewpoint')}"].append(r)
                cond[f"quality={a.get('image_quality')}"].append(r)
                for art in a.get("visual_artifacts") or []:
                    cond[f"artifact={art}"].append(r)
                cond[f"domain={(a.get('client') or '').split('_')[-1]}"].append(r)
        s["by_condition"] = {k: stats(v) for k, v in sorted(cond.items()) if len(v) >= 5}
        tags = defaultdict(list)
        for r in rows:
            for t in r.get("tags") or []:
                tags[t.split(":")[0]].append(r)
        s["by_tag"] = {k: stats(v) for k, v in sorted(tags.items())}
        summary["sets"][sub] = s
    pu = runs / f"{args.label}_unusable.jsonl"
    if pu.is_file():
        rows = load(pu)
        by = defaultdict(list)
        for r in rows:
            by[r.get("degrade")].append(r)
        un = {k: {"n": len(v), "correct_refusal_rate": len([r for r in v if not r.get("valid")]) / len(v),
                  "refusal_reasons": dict(Counter(r.get("invalid_reason") for r in v if not r.get("valid")))}
              for k, v in sorted(by.items())}
        tot = [r for r in rows if "error" not in r]
        un["overall"] = {"n": len(tot), "correct_refusal_rate": len([r for r in tot if not r.get("valid")]) / len(tot),
                         "target": ">= 0.95"}
        summary["unusable"] = un
    out = Path(args.out) if args.out else runs / f"{args.label}_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for sub, s in summary["sets"].items():
        o = s["overall"]
        print(f"[{sub}] n={o['n']} det={o['det_rate'] and round(o['det_rate'], 3)} valid={round(o['valid_rate'], 3)} "
              f"mean={o['mean_err_norm'] and round(o['mean_err_norm'] * 100, 2)}% med={o['median_err_norm'] and round(o['median_err_norm'] * 100, 2)}% "
              f"p95={o['p95_err_norm'] and round(o['p95_err_norm'] * 100, 2)}% gross(valid)={o['gross_rate_valid'] and round(o['gross_rate_valid'] * 100, 1)}% "
              f"reasons={o['refusal_reasons']} causes={o['gross_causes']}")
    if "unusable" in summary:
        print("[unusable]", {k: round(v["correct_refusal_rate"], 3) for k, v in summary["unusable"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
