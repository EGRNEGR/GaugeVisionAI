"""
Миграция КОПИЙ реальных локальных баз прежних версий новым кодом (оригиналы не открываются на запись).

Для каждой базы: копия во временный каталог, подсчёт строк всех таблиц, db.init_db() объединённой ветки
(дважды — проверка идемпотентности), повторный подсчёт, проверка: ни одна таблица не потеряла строк, у каждой
камеры есть основной прибор, у всех строк readings заполнен instrument_id, история читается
get_instrument_series. В доказательство пишутся только счётчики (без содержимого баз).

    python migrate_copies.py <db1> [<db2> ...] --out migration_copies.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def counts(path: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in sorted(tabs)}
    finally:
        con.close()


async def migrate(path: Path) -> dict[str, object]:
    os.environ["GAUGEVISION_DB"] = str(path)
    sys.path.insert(0, str(ROOT))
    from app import db
    await db.init_db()
    await db.close_db()
    await db.init_db()
    cams = await db.list_cameras()
    insts = await db.list_instruments()
    series = await db.get_instrument_series([c["id"] for c in cams], since_iso="2000-01-01T00:00:00+00:00",
                                            max_per_instrument=10**7) if cams else {}
    await db.close_db()
    return {"cameras": len(cams), "primary_instruments": sum(1 for i in insts if i["is_primary"]),
            "series_points": sum(len(v) for v in series.values())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dbs", nargs="+")
    ap.add_argument("--out", default=str(Path(__file__).with_name("migration_copies.json")))
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="gv_mig_copies_"))
    results = []
    for k, src in enumerate(args.dbs):
        src_p = Path(src)
        dst = work / f"copy_{k}.db"
        con = sqlite3.connect(f"file:{src_p}?mode=ro", uri=True)
        bk = sqlite3.connect(dst)
        con.backup(bk)  # согласованная копия даже при активном WAL оригинала
        bk.close()
        con.close()
        before = counts(dst)
        info = asyncio.run(migrate(dst))
        after = counts(dst)
        lost = {t: [n, after.get(t)] for t, n in before.items() if after.get(t, 0) < n}
        con = sqlite3.connect(dst)
        null_inst = con.execute("SELECT COUNT(*) FROM readings WHERE instrument_id IS NULL").fetchone()[0] \
            if "readings" in after else None
        valid_readings = con.execute("SELECT COUNT(*) FROM readings WHERE value IS NOT NULL").fetchone()[0] \
            if "readings" in after else 0
        con.close()
        res = {"source": src_p.name, "source_dir": src_p.parent.name, "tables_before": len(before),
               "tables_after": len(after), "rows_before": before, "rows_after": after, "lost_rows": lost,
               "readings_without_instrument_id": null_inst, "valid_readings": valid_readings, **info,
               "passed": not lost and null_inst in (0, None) and info["primary_instruments"] >= info["cameras"]}
        results.append(res)
        print(f"[{'PASS' if res['passed'] else 'FAIL'}] {src_p.parent.name}/{src_p.name}: tables {len(before)}→{len(after)}, "
              f"readings {before.get('readings')}→{after.get('readings')}, cameras {info['cameras']}, "
              f"primary {info['primary_instruments']}, series {info['series_points']}/{valid_readings}, lost {lost}")
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
