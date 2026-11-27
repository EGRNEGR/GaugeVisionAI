"""
Статический скан кода (REQ-ARCH-01): заглушки, незавершённые фрагменты, абсолютные пути,
символ middle dot в интерфейсе. Сканируются приложение, интерфейс, точка запуска, скрипты
развёртывания и переносимые проверочные скрипты повторной приёмки.

  python reports/final_integration/evidence/static/static_scan_final.py
Результат: reports/final_integration/evidence/static/static_scan.json (цели расширены каталогом evidence интеграционной приёмки)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TARGETS = ["app", "static", "run.py", "scripts", "tests", "reports/remediation/tests", "reports/final_integration/evidence"]
EXTS = {".py", ".js", ".html", ".css", ".ps1"}
PATTERNS = {
    "todo_fixme": re.compile(r"\b(TODO|FIXME|XXX|HACK)\b"),
    "not_implemented": re.compile(r"NotImplementedError|raise\s+NotImplemented\b"),
    "absolute_windows_path": re.compile(r"[\"'][A-Za-z]:\\\\[^\"']*[\"']|[\"'][A-Za-z]:/[^\"']*[\"']"),
    "absolute_user_path": re.compile(r"(?i)c:[\\/]+users[\\/]"),
}
UI_EXTS = {".js", ".html", ".css"}
# файлы, которые содержат названия шаблонов как данные (сам сканер и генератор матрицы)
SELF_REFERENCING = {"static_scan.py", "static_scan_final.py", "build_rtm.py", "build_rtm_final.py"}
# намеренные атакующие пути в тестах Path Traversal и примеры запуска в справке скриптов
ALLOWED_MARKERS = ("win.ini", "--base-python")


def main() -> None:
    findings: dict[str, list[str]] = {k: [] for k in PATTERNS}
    findings["middle_dot_in_ui"] = []
    files = 0
    for t in TARGETS:
        p = ROOT / t
        paths = [p] if p.is_file() else [q for q in p.rglob("*") if q.is_file()]
        for f in paths:
            if f.suffix not in EXTS or "__pycache__" in f.parts or f.name in SELF_REFERENCING:
                continue
            files += 1
            rel = str(f.relative_to(ROOT)).replace("\\", "/")
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for name, rx in PATTERNS.items():
                    if rx.search(line):
                        # примеры путей в справке argparse/документации скрипта не являются зашитыми путями
                        if name.startswith("absolute") and (line.lstrip().startswith(("#", "python", "powershell", "<"))
                                                            or "help=" in line or any(m in line for m in ALLOWED_MARKERS)):
                            continue
                        findings[name].append(f"{rel}:{i}: {line.strip()[:140]}")
                if f.suffix in UI_EXTS and rel.startswith("static/") and "·" in line:
                    findings["middle_dot_in_ui"].append(f"{rel}:{i}")
    res = {"files_scanned": files, "targets": TARGETS, "findings": findings,
           "clean": all(not v for v in findings.values())}
    out = ROOT / "reports" / "final_integration" / "evidence" / "static" / "static_scan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"files": files, "clean": res["clean"], **{k: len(v) for k, v in findings.items()}}, ensure_ascii=False))
    for k, v in findings.items():
        for x in v[:10]:
            print(k, x)


if __name__ == "__main__":
    main()
