"""
Сверка экономики ТЗ на случае 3 исходного audit_03 (регулярные перегрузки, газовая зона).

audit_03 сравнивает годовой эффект с формулой без OPEX и потому после введения OPEX (DEF-04)
даёт annual_effect_match / payback_years_match = False. Скрипт пересчитывает ту же формулу аудита,
вычитает OPEX и сверяет CAPEX, валовой и чистый эффект и окупаемость с генератором.

  python reports/remediation/tests/economics_reconcile_audit03.py
"""
import asyncio, json, os, sys, tempfile, importlib.util
from pathlib import Path
root = Path(__file__).resolve().parents[3]
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ["AUDIT_OUT_DIR"] = tempfile.mkdtemp(prefix="gv_a3_")
OUT = root / "reports" / "remediation" / "evidence" / "original_audit_rerun" / "economics_reconciliation.json"
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location("a3", root / "reports/audit/tests/audit_03_track1_dispatch_specs_security.py")
a3 = importlib.util.module_from_spec(spec); spec.loader.exec_module(a3)
from app.dispatch_analyzer import DispatchAnalyzer
from app.spec_generator import generate_spec_bundle
from app import config
async def main():
    da = DispatchAnalyzer()
    mk = a3.make_inst
    gas = [mk(iid="g1", code="ГРП-Р01", group="Топливо и тяга", gauge_type="pressure", unit="МПа", v_min=0, v_max=1.0, value=0.68, level="alert"),
           mk(iid="g2", code="ТА2-Т02", group="Турбоагрегаты", gauge_type="temperature", unit="°C", v_min=0, v_max=120, value=95.0, level="alert")]
    b = await generate_spec_bundle(dispatch_overview=da.overview(gas, []), events=[], snapshot_lookup={}, period="12h")
    e = b["economics"]; t = b["tz_items"]
    hw = sum(r["replacement"]["unit_cost_rub"] for r in t); smr = sum(r["replacement"]["install_cost_rub"] for r in t)
    capex = hw + smr + int(round((hw + smr) * 0.14))
    gross_audit = sum(r["risk_saved_rub"] for r in t) + len(t) * 38_000
    opex = len(t) * config.ECO_OPEX_PER_SENSOR_RUB_YR
    net = max(0, gross_audit - opex)
    res = {"n_items": len(t), "capex_gen": e["capex_rub"], "capex_audit_formula": capex,
        "gross_gen": e["gross_annual_effect_rub"], "gross_audit_formula": gross_audit,
        "opex_gen": e["opex_rub_yr"], "opex_expected": opex, "net_gen": e["annual_effect_rub"], "net_expected": net,
        "payback_years_gen": e["payback_years"], "payback_expected": round(capex / net, 2) if net else None,
        "payback_months_gen": e["payback_months"]}
    res["all_match"] = (res["capex_gen"] == res["capex_audit_formula"] and res["gross_gen"] == res["gross_audit_formula"]
                        and res["opex_gen"] == res["opex_expected"] and res["net_gen"] == res["net_expected"]
                        and res["payback_years_gen"] == res["payback_expected"])
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res["all_match"] else 1
sys.exit(asyncio.run(main()))
