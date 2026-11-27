"""
Независимый аудит промышленной кибербезопасности GaugeVision AI на локальном изолированном стенде.
Проверяет RBAC, аутентификацию, защиту RTSP credentials, SSRF/Path Traversal, валидацию и защиту
от злоупотреблений новых аналитических и оптимизационных API, безопасность Modbus/MQTT/DOCX/CSV
и автономность air-gapped развёртывания.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sqlite3
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["GAUGEVISION_DEVICE"] = "cpu"

OUT_DIR = Path(__file__).resolve().parent


def _probe_modbus_pdu(mb_gw: Any, unit_id: int, pdu: bytes) -> tuple[int, int]:
    """Проверяет обработчик Modbus TCP локально на loopback без внешних хостов."""
    async def _run() -> tuple[int, int]:
        from app import config
        orig_en, orig_port = config.MODBUS_ENABLED, config.MODBUS_PORT
        config.MODBUS_ENABLED = True
        config.MODBUS_PORT = 0
        srv = await asyncio.start_server(mb_gw._handle_client, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            mbap = struct.pack(">HHHB", 1, 0, len(pdu) + 1, unit_id)
            w.write(mbap + pdu)
            await w.drain()
            rhdr = await r.readexactly(7)
            _, _, rlen, _ = struct.unpack(">HHHB", rhdr)
            rpdu = await r.readexactly(rlen - 1)
            w.close()
            await w.wait_closed()
            return rpdu[0], rpdu[1]
        finally:
            srv.close()
            await srv.wait_closed()
            config.MODBUS_ENABLED, config.MODBUS_PORT = orig_en, orig_port

    return asyncio.run(_run())


def run_security_audit() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def rec(cid: str, category: str, title: str, passed: bool, detail: str, severity: str = "info") -> None:
        checks.append({
            "id": cid, "category": category, "title": title,
            "passed": bool(passed), "severity": severity, "detail": detail,
        })

    with tempfile.TemporaryDirectory(prefix="gv_sec_audit_") as tmp:
        db_file = Path(tmp) / "sec_audit.db"
        sf_file = Path(tmp) / "sec_sf.db"
        orig_env = {k: os.environ.get(k) for k in ("GAUGEVISION_DEMO", "GAUGEVISION_DB", "GAUGEVISION_SF_DB", "GAUGEVISION_AUTH_REQUIRED")}
        os.environ["GAUGEVISION_DEMO"] = "1"
        os.environ["GAUGEVISION_DB"] = str(db_file)
        os.environ["GAUGEVISION_SF_DB"] = str(sf_file)
        os.environ["GAUGEVISION_AUTH_REQUIRED"] = "1"
        try:
            from app import config, main as gv_main
            config.configure_runtime(demo=True, db_path=str(db_file), device="cpu")

            with TestClient(gv_main.app) as client:
                # 1. Unauthenticated access blocked (401)
                unauth_eps = [
                    ("GET", "/api/predictive/overview"),
                    ("GET", "/api/passports"),
                    ("GET", "/api/optimizer/plans"),
                    ("POST", "/api/optimizer/solve"),
                    ("PATCH", "/api/passports/sim-02"),
                ]
                unauth_codes = {}
                for m, ep in unauth_eps:
                    r = client.request(m, ep, json={"budget_rub": 100000} if m in ("POST", "PATCH") else None)
                    unauth_codes[f"{m} {ep}"] = r.status_code
                rec(
                    "SEC-01", "Auth/RBAC", "Блокировка неаутентифицированного доступа к новым API (HTTP 401)",
                    all(c == 401 for c in unauth_codes.values()),
                    json.dumps(unauth_codes), severity="high",
                )

                # 2. Security headers & CSP & non-wildcard CORS
                r_idx = client.get("/")
                hdrs = {k.lower(): v for k, v in r_idx.headers.items()}
                sec_hdrs_ok = (
                    hdrs.get("x-frame-options") == "DENY"
                    and hdrs.get("x-content-type-options") == "nosniff"
                    and "frame-ancestors 'none'" in hdrs.get("content-security-policy", "")
                    and hdrs.get("access-control-allow-origin") != "*"
                )
                rec("SEC-02", "HTTP Hardening", "Защитные заголовки CSP / X-Frame-Options / nosniff / отсутствие CORS *",
                    sec_hdrs_ok, f"XFO={hdrs.get('x-frame-options')}, XCTO={hdrs.get('x-content-type-options')}")

                # Login tokens for 3 roles
                def _login(u: str, p: str) -> str:
                    rl = client.post("/api/auth/login", json={"username": u, "password": p})
                    assert rl.status_code == 200, rl.text
                    return rl.json()["token"]

                tok_op = _login(config.OPERATOR_USERNAME, config.OPERATOR_PASSWORD)
                tok_eng = _login(config.ENGINEER_USERNAME, config.ENGINEER_PASSWORD)
                tok_adm = _login(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)
                h_op = {"Authorization": f"Bearer {tok_op}"}
                h_eng = {"Authorization": f"Bearer {tok_eng}"}
                h_adm = {"Authorization": f"Bearer {tok_adm}"}

                # 3. RBAC enforcement on Analytics / Optimizer / Passports
                r_op_read = client.get("/api/predictive/overview", headers=h_op)
                r_op_solve = client.post("/api/optimizer/solve", json={"budget_rub": 300_000}, headers=h_op)
                r_op_save = client.post("/api/optimizer/plans", json={"name": "hack", "budget_rub": 300_000}, headers=h_op)
                r_op_pass = client.patch("/api/passports/sim-02", json={"mandatory_regulation": True}, headers=h_op)
                r_eng_solve = client.post("/api/optimizer/solve", json={"budget_rub": 300_000}, headers=h_eng)
                r_eng_audit = client.get("/api/auth/audit", headers=h_eng)
                r_adm_audit = client.get("/api/auth/audit", headers=h_adm)
                rbac_ok = (
                    r_op_read.status_code == 200
                    and r_op_solve.status_code == 403
                    and r_op_save.status_code == 403
                    and r_op_pass.status_code == 403
                    and r_eng_solve.status_code == 200
                    and r_eng_audit.status_code == 403
                    and r_adm_audit.status_code == 200
                )
                rec("SEC-03", "Auth/RBAC", "Разграничение прав operator / engineer / admin на аналитике и оптимизаторе",
                    rbac_ok,
                    f"op_read={r_op_read.status_code}, op_solve={r_op_solve.status_code}, op_save={r_op_save.status_code}, "
                    f"op_pass={r_op_pass.status_code}, eng_solve={r_eng_solve.status_code}, eng_audit={r_eng_audit.status_code}, adm_audit={r_adm_audit.status_code}",
                    severity="high")

                # 4. Brute-force lockout on /api/auth/login
                bf_codes = []
                for _ in range(config.LOGIN_MAX_FAILURES + 1):
                    rb = client.post("/api/auth/login", json={"username": "attacker_user", "password": "wrong"})
                    bf_codes.append(rb.status_code)
                rec("SEC-04", "Auth/RBAC", "Защита входа от перебора паролей (lockout HTTP 429)",
                    bf_codes[-1] == 429, f"codes={bf_codes}", severity="medium")

                # 5. Optimizer Abuse / DoS / Invalid Economic Parameters Fuzzing
                bad_payloads = [
                    ("neg_budget", {"budget_rub": -50_000}),
                    ("huge_budget", {"budget_rub": 999_999_999_999}),
                    ("excess_time_limit", {"budget_rub": 300_000, "time_limit_s": 999.0}),
                    ("huge_mandatory_list", {"budget_rub": 300_000, "mandatory_ids": [f"x{i}" for i in range(300)]}),
                    ("huge_dependencies", {"budget_rub": 300_000, "dependencies": {f"k{i}": ["a"] for i in range(260)}}),
                    ("neg_min_per_group", {"budget_rub": 300_000, "min_per_group": {"G1": -2}}),
                    ("bad_eco_comm_rate", {"budget_rub": 300_000, "economics_config": {"commissioning_rate": 5.5}}),
                    ("bad_eco_risk_mult", {"budget_rub": 300_000, "economics_config": {"downtime_risk_multiplier": -1.0}}),
                    ("bad_objective", {"budget_rub": 300_000, "objective": "DROP TABLE modernization_plans"}),
                ]
                fuzz_res = {}
                for bname, pl in bad_payloads:
                    rf = client.post("/api/optimizer/solve", json=pl, headers=h_eng)
                    fuzz_res[bname] = rf.status_code
                rec("SEC-05", "Input Validation / DoS", "Отклонение некорректных/ресурсоёмких запросов к оптимизатору (HTTP 422, ноль HTTP 500)",
                    all(c == 422 for c in fuzz_res.values()), json.dumps(fuzz_res), severity="high")

                # 6. Passport tampering & XML control-char injection into DOCX
                r_bad_date = client.patch("/api/passports/sim-02", json={"verification_due_date": "not-a-date"}, headers=h_eng)
                r_bad_capex = client.patch("/api/passports/sim-02", json={"custom_capex_rub": -1000}, headers=h_eng)
                r_ctrl_note = client.patch("/api/passports/sim-02", json={"notes": "Тест\x00\x07<script>alert(1)</script>"}, headers=h_eng)
                r_spec_xml = client.post(
                    "/api/specs/generate",
                    json={"period": "12h", "format": "docx", "plant_name": "ТЭЦ\x00\x0b<&>"},
                    headers=h_eng,
                )
                xml_valid = False
                if r_spec_xml.status_code == 200:
                    with zipfile.ZipFile(io.BytesIO(r_spec_xml.content)) as zf:
                        ET.fromstring(zf.read("word/document.xml"))
                        xml_valid = True
                rec("SEC-06", "DOCX / Input Validation", "Защита паспортов и генератора DOCX от XML-инъекций и управляющих байтов",
                    r_bad_date.status_code == 422 and r_bad_capex.status_code == 422 and r_ctrl_note.status_code == 200 and xml_valid,
                    f"bad_date={r_bad_date.status_code}, bad_capex={r_bad_capex.status_code}, docx_valid_xml={xml_valid}",
                    severity="medium")

                # 7. Cross-instrument / SQLi probing & immutable plans
                r_sqli = client.get("/api/predictive/history/' OR 1=1--", headers=h_op)
                r_ctrl_id = client.get("/api/predictive/history/abc%00def", headers=h_op)
                r_del_plan = client.delete("/api/optimizer/plans/1", headers=h_adm)
                rec("SEC-07", "IDOR / Injection", "Параметризация SQLite, проверка inst_id и неизменяемость сохранённых планов",
                    r_sqli.status_code == 404 and r_ctrl_id.status_code == 422 and r_del_plan.status_code == 405,
                    f"sqli={r_sqli.status_code}, ctrl_id={r_ctrl_id.status_code}, del_plan={r_del_plan.status_code}",
                    severity="medium")

                # 8. RTSP credentials encryption at rest + SSRF + Path Traversal
                r_ssrf = client.post("/api/cameras", json={"name": "SSRF", "type": "rtsp", "source_url": "rtsp://169.254.169.254/latest"}, headers=h_eng)
                r_trav = client.post("/api/cameras", json={"name": "PT", "type": "video_file", "source_url": "../../Windows/win.ini"}, headers=h_eng)
                r_rtsp = client.post("/api/cameras", json={"name": "LAN Cam", "type": "rtsp", "source_url": "rtsp://admin:SuperSecret99@192.168.10.55:554/stream"}, headers=h_eng)
                rtsp_masked = r_rtsp.status_code == 201 and "SuperSecret99" not in r_rtsp.text and "***:***@" in r_rtsp.text
                con = sqlite3.connect(str(db_file))
                raw_urls = [row[0] for row in con.execute("SELECT source_url FROM cameras WHERE source_url IS NOT NULL").fetchall()]
                con.close()
                rtsp_encrypted = any(str(u).startswith("enc:v1:") for u in raw_urls) and all("SuperSecret99" not in str(u) for u in raw_urls)
                rec("SEC-08", "RTSP / SSRF / Path Traversal", "Шифрование RTSP credentials в SQLite (Fernet), маскирование в API, блокировка SSRF и Path Traversal",
                    r_ssrf.status_code == 422 and r_trav.status_code == 422 and rtsp_masked and rtsp_encrypted,
                    f"ssrf={r_ssrf.status_code}, trav={r_trav.status_code}, masked={rtsp_masked}, enc_at_rest={rtsp_encrypted}",
                    severity="high")

                # 9. Audit log captures analytics & forbidden attempts
                audit_rows = client.get("/api/auth/audit?limit=50", headers=h_adm).json()
                actions = {r["action"] for r in audit_rows}
                rec("SEC-09", "Audit Logging", "Фиксация действий оптимизатора, паспортов и отказов RBAC в audit_log",
                    "OPTIMIZER_SOLVE" in actions and "PASSPORT_UPDATE" in actions and any(a.startswith("FORBIDDEN ") for a in actions),
                    f"recorded_actions={sorted(actions)[:12]}", severity="medium")

            # 10. Modbus TCP Read-Only & Unit ID & Range Enforcement
            from app.scada_gateway import ModbusTcpGateway
            mb = ModbusTcpGateway()
            fc_w, ex_w = _probe_modbus_pdu(mb, 1, struct.pack(">BHH", 6, 0, 123))      # FC 0x06 Write Single -> 0x86, 0x01
            fc_u, ex_u = _probe_modbus_pdu(mb, 99, struct.pack(">BHH", 3, 0, 2))       # Wrong Unit ID -> 0x83, 0x0B
            fc_r, ex_r = _probe_modbus_pdu(mb, 1, struct.pack(">BHH", 3, 4095, 2))     # Out of range -> 0x83, 0x02
            rec("SEC-10", "SCADA / Modbus", "Режим только на чтение Modbus TCP (FC 0x06 -> 0x01), Unit ID (0x0B) и границы карты (0x02)",
                (fc_w == 0x86 and ex_w == 0x01) and (fc_u == 0x83 and ex_u == 0x0B) and (fc_r == 0x83 and ex_r == 0x02),
                f"write=({hex(fc_w)},{hex(ex_w)}), unit99=({hex(fc_u)},{hex(ex_u)}), oor=({hex(fc_r)},{hex(ex_r)})",
                severity="high")

            # 11. Air-gapped static assets check (no external CDN scripts/styles/fonts)
            static_dir = ROOT / "static"
            ext_cdn_refs = []
            ext_anchor_links = []
            cdn_tag_re = re.compile(r"<(?:script|link|img)[^>]*(?:src|href)\s*=\s*['\"]https?://[^'\"]+", re.IGNORECASE)
            anchor_re = re.compile(r"<a[^>]*href\s*=\s*['\"]https?://[^'\"]+", re.IGNORECASE)
            for fp in static_dir.rglob("*"):
                if fp.suffix.lower() in (".html", ".js", ".css"):
                    txt = fp.read_text(encoding="utf-8", errors="ignore")
                    for m in cdn_tag_re.finditer(txt):
                        ext_cdn_refs.append(f"{fp.name}:{m.group(0)[:80]}")
                    for m in anchor_re.finditer(txt):
                        ext_anchor_links.append(f"{fp.name}:{m.group(0)[:80]}")
            rec("SEC-11", "Air-Gapped Deployment", "Отсутствие внешних CDN-ресурсов (script/link/img) в статических файлах HMI",
                len(ext_cdn_refs) == 0,
                f"external_cdn_assets={ext_cdn_refs}, informational_anchor_links={len(ext_anchor_links)}",
                severity="medium")

        finally:
            for k, v in orig_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    # Задокументированные системные/общие замечания для агента интеграции (без вмешательства в чужие модули)
    shared_observations = [
        {
            "id": "OBS-SHARED-01",
            "severity": "medium",
            "component": "app/config.py (HOST = '0.0.0.0')",
            "finding": "По умолчанию HTTP/HTTPS сервер слушает все сетевые интерфейсы (0.0.0.0:8443). Для промышленного АСУ ТП рекомендуется явная привязка GAUGEVISION_HOST к выделенному VLAN-интерфейсу.",
        },
        {
            "id": "OBS-SHARED-02",
            "severity": "medium",
            "component": "app/config.py (MQTT_TLS = False)",
            "finding": "MQTT TLS отключён по умолчанию (GAUGEVISION_MQTT_TLS=0). При передаче телеметрии и учётных данных вне loopback необходимо принудительно включать TLS и проверку сертификата брокера.",
        },
        {
            "id": "OBS-SHARED-03",
            "severity": "low",
            "component": "app/scada_gateway.py (Modbus TCP plaintext / no IP ACL)",
            "finding": "Протокол Modbus TCP по стандарту не содержит аутентификации и шифрования. По умолчанию шлюз безопасно привязан к 127.0.0.1:15020; при выносе на LAN обязательна сетевая сегментация (firewall/VLAN allowlist на IP SCADA-сервера).",
        },
        {
            "id": "OBS-SHARED-04",
            "severity": "low",
            "component": "app/spec_generator.py (_try_llm_enrichment)",
            "finding": "Опциональный режим llm_enhanced отправляет POST на GAUGEVISION_LLM_BASE_URL (задаётся администратором через env) без дополнительной SSRF-фильтрации URL; в air-gapped контуре переменная пуста и используется deterministic-режим.",
        },
        {
            "id": "OBS-SHARED-05",
            "severity": "low",
            "component": "app/config.py (SIMULATOR_URL, candidate_lan_ips 8.8.8.8 probe)",
            "finding": "SIMULATOR_URL указывает на внешний URL в качестве справочной ссылки UI (бэкендом не запрашивается); candidate_lan_ips использует UDP connect('8.8.8.8', 80) без отправки пакетов для определения локального маршрута (при отсутствии шлюза безопасно падает на частные сети / 127.0.0.1).",
        },
    ]

    passed_cnt = sum(1 for c in checks if c["passed"])
    report = {
        "total_checks": len(checks),
        "passed_checks": passed_cnt,
        "all_passed": passed_cnt == len(checks),
        "checks": checks,
        "shared_observations_for_integration": shared_observations,
    }
    (OUT_DIR / "security_audit_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SECURITY AUDIT: {passed_cnt}/{len(checks)} PASSED")
    for c in checks:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['id']} ({c['category']}): {c['title']} -> {c['detail'][:120]}")
    return report


if __name__ == "__main__":
    run_security_audit()
