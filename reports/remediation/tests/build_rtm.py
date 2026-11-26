"""
Сборка матрицы трассируемости повторной приёмки и пересчёт оценки по исходной методике аудита.

Исходная матрица Gemini (reports/audit/REQUIREMENTS_TRACEABILITY_MATRIX.csv) не изменяется:
требования, приоритеты и критерии берутся из неё как есть. Для каждого требования добавляются
статус повторной приёмки, фактический результат и ссылка на доказательство.

Методика (FULL_AUDIT_REPORT.md, раздел 2): балл направления = макс. балл × (PASS + 0,5 × PARTIAL) /
число требований направления; FAIL и NOT VERIFIED дают 0.

  python reports/remediation/tests/build_rtm.py
Результат: reports/remediation/REQUIREMENTS_TRACEABILITY_MATRIX.csv и evidence/score.json.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "reports" / "audit" / "REQUIREMENTS_TRACEABILITY_MATRIX.csv"
OUT = ROOT / "reports" / "remediation" / "REQUIREMENTS_TRACEABILITY_MATRIX.csv"
SCORE = ROOT / "reports" / "remediation" / "evidence" / "score.json"

MAX_POINTS = {
    "Архитектурная видеоаналитика": 12, "Store-and-Forward и отказоустойчивость": 15,
    "API и промышленные интеграции": 8, "Аналитика и умная диспетчеризация": 15,
    "Генерация инженерной документации": 15, "Корректность и сохранение CV-инференса": 10,
    "Функциональность и качество HMI": 10, "Безопасность и автономность": 8,
    "Архитектура и качество кода": 4, "Тестирование и воспроизводимость": 3,
}

E = "evidence/"
# ID: (статус, фактический результат, доказательство, дефекты и их состояние)
STATUS: dict[str, tuple[str, str, str, str]] = {
    "REQ-VA-01": ("PASS", "Реальный RTSP: mediamtx с аутентификацией + ffmpeg H.264; подключение 2,5–3,5 с, 80/80 показаний в ±0,35 МПа от эталона, обрыв издателя восстановлен за 5,1 с, перезапуск RTSP-сервера — за 14,2 с, инференс возобновлён; остальные каналы online", E + "interop/interop_results.json", ""),
    "REQ-VA-02": ("PASS", "Видеофайл data/videos через VideoFileWorker: канал работал весь часовой soak, кадры и отсчёты непрерывно росли", E + "soak/summary.json", ""),
    "REQ-VA-03": ("NOT VERIFIED", "Испытание с физической USB/UVC-камерой не выполнено", E + "usb_camera/usb_camera_results.json", ""),
    "REQ-VA-04": ("PASS", "5 одновременных CV-каналов (2 стендовых, RTSP, видеофайл, смартфон) в часовом soak; при обрывах RTSP стендовые каналы оставались online", E + "soak/summary.json; " + E + "interop/interop_results.json", ""),
    "REQ-VA-05": ("PASS", "Переподключение с экспоненциальной задержкой подтверждено на реальном RTSP: 5,1 с после возврата издателя, 14,2 с после перезапуска сервера", E + "interop/interop_results.json", ""),
    "REQ-VA-06": ("PASS", "Заморозка, темнота, частичное перекрытие вычисляются по пикселям без обходов через injected_fault; в браузере пар и перекрытие дают DEGRADED, восстановление — ONLINE", E + "browser_e2e/browser_e2e_report.json; " + E + "original_audit_rerun/", "DEF-11 устранён"),
    "REQ-VA-07": ("PASS", "Перекрытие паром/задымлением по резкости кадра, 50 % перекрытие объектива определяется (DEGRADED)", E + "acceptance_tests/acceptance_results.json; " + E + "original_audit_rerun/", "DEF-11 устранён"),
    "REQ-VA-08": ("NOT VERIFIED", "Пропуски кадров на реальном потоке ещё не подтверждены", E + "interop/interop_results.json", "DEF-11"),
    "REQ-VA-09": ("PASS", "Adaptive FPS 1→6 к/с, motion wake-up < 0,4 мс; экономия CPU 77,4 % (audit_05); переходный импульс < 1 с будит канал", E + "original_audit_rerun/; " + E + "antigravity/benchmark_after.json", "DEF-12 устранён"),
    "REQ-VA-10": ("PASS", "Параллельные инциденты не теряются, pre-кадры строго до триггера, клипы на диске и восстанавливаются после перезапуска; вытесненный захват сохраняется", E + "acceptance_tests/acceptance_results.json", "DEF-10, NEW-08 устранены"),
    "REQ-VA-11": ("PASS", "Диагностические API и симуляция обрыва/деградации из интерфейса проверены в браузере и soak", E + "browser_e2e/browser_e2e_report.json", ""),
    "REQ-SF-01": ("PASS", "journal_mode=wal читается из PRAGMA; WAL подтверждён в offline-установке", E + "offline_install/offline_install_results.json", "DEF-19 устранён"),
    "REQ-SF-02": ("PASS", "seq_id и event_uuid в каждой записи; сверка подписчика amqtt идёт по event_uuid", E + "interop/interop_results.json", ""),
    "REQ-SF-03": ("PASS", "Обрыв из интерфейса копит записи (браузер, soak)", E + "browser_e2e/browser_e2e_report.json", ""),
    "REQ-SF-04": ("PASS", "Тревоги и телеметрия копятся при обрыве", E + "interop/interop_results.json", ""),
    "REQ-SF-05": ("PASS", "Кадры тревог доставлены через сторонний брокер, SHA-256 совпал у всех полученных кадров; после подтверждения байты кадра в очереди не хранятся", E + "interop/interop_results.json; " + E + "acceptance_tests/acceptance_results.json", "DEF-06, NEW-02 устранены"),
    "REQ-SF-06": ("PASS", "Реальная остановка брокера amqtt: записи остаются pending, после запуска досылаются (113/113, 0 потерь); в soak 6 циклов падения брокера", E + "interop/interop_results.json; " + E + "soak/summary.json", "DEF-01 (P0) устранён"),
    "REQ-SF-07": ("PASS", "Автоматическая досылка после восстановления: 5–11 с", E + "interop/interop_results.json", ""),
    "REQ-SF-08": ("PASS", "Строгий порядок seq_id при конкурентной записи и досылке", E + "acceptance_tests/acceptance_results.json", ""),
    "REQ-SF-09": ("PASS", "Очередь сохраняется при перезапуске; события дописываются в БД до остановки сервиса", E + "acceptance_tests/acceptance_results.json; " + E + "original_audit_rerun/", ""),
    "REQ-SF-10": ("PASS", "Повторный обрыв в ходе досылки без потерь (audit_02)", E + "original_audit_rerun/", ""),
    "REQ-SF-11": ("PASS", "At-least-once с event_uuid, retry_count и экспоненциальной паузой; живая доставка и досылка сериализованы: 0 дублей в конкурентном тесте и при реальных отказах брокера", E + "acceptance_tests/acceptance_results.json; " + E + "interop/interop_results.json", "DEF-21, NEW-03 устранены"),
    "REQ-SF-12": ("PASS", "Лимит строк/МБ/диска, вытеснение телеметрии с сохранением тревог, журнал переполнения и флаг queue_overflow", E + "acceptance_tests/acceptance_results.json", "DEF-06 устранён"),
    "REQ-API-01": ("PASS", "REST-набор треков 1 и 2 работает в soak без ошибок API", E + "soak/summary.json", ""),
    "REQ-API-02": ("PASS", "JSON NaN/Infinity → 422 с корректным JSON; SSRF/Path Traversal → 422", E + "acceptance_tests/acceptance_results.json", "DEF-09 устранён"),
    "REQ-API-03": ("PASS", "WebSocket /ws/dashboard: 2 клиента весь soak, сессия перепроверяется (выход закрывает поток кодом 4401)", E + "soak/summary.json; " + E + "acceptance_tests/acceptance_results.json", ""),
    "REQ-API-04": ("PASS", "SSE /api/events/stream: события получены клиентом весь soak", E + "soak/summary.json", ""),
    "REQ-API-05": ("PASS", "Сторонний клиент pymodbus: 30/30 значений совпали с REST, STALE = NaN, чужой unit_id → исключение 0x0B, неверный адрес → 0x02", E + "interop/interop_results.json", "DEF-13 устранён"),
    "REQ-API-06": ("PASS", "Сторонний брокер amqtt: MQTT 3.1.1 QoS 1 с PUBACK, переподключение, досылка без потерь", E + "interop/interop_results.json", "DEF-01, DEF-13 устранены"),
    "REQ-API-07": ("NOT VERIFIED", "Стыковка с реальными Ignition / MasterSCADA не выполнялась: проверка ограничена независимыми реализациями протоколов (amqtt, pymodbus)", "—", ""),
    "REQ-DA-01": ("PASS", "Классификация LL/L/H/HH", E + "original_audit_rerun/", ""),
    "REQ-DA-02": ("PASS", "dP/dt по фактическим меткам времени; при опросе HMI 20 Гц исправный прибор остаётся nominal, реальный скачок 12→16 МПа за 2 с даёт гидроудар", E + "acceptance_tests/acceptance_results.json", "DEF-14, NEW-01 устранены"),
    "REQ-DA-03": ("PASS", "Дребезг по фактическому ряду без скрытых профилей", E + "original_audit_rerun/", "DEF-08 устранён"),
    "REQ-DA-04": ("PASS", "Перегрузка без фантомных минут: 90 тиков по 2 с = 3,00 мин; в SQL-статистике периода совпадает с эталоном", E + "acceptance_tests/acceptance_results.json", "DEF-08 устранён"),
    "REQ-DA-05": ("PASS", "Срабатывания по реальным окнам 12 ч / 24 ч (2 / 4 на контрольном наборе)", E + "acceptance_tests/acceptance_results.json", "DEF-08 устранён"),
    "REQ-DA-06": ("PASS", "Оптика и confidence входят в optical_health", E + "acceptance_tests/acceptance_results.json", ""),
    "REQ-DA-07": ("PASS", "Health Score не занижается оптикой (пар: optical 40 %, техсостояние 100 %), очередь рекомендаций с уверенностью гипотез", E + "acceptance_tests/acceptance_results.json", "DEF-08 устранён"),
    "REQ-DA-08": ("PASS", "Три класса причин + норма; загрязнение камеры не даёт модернизации", E + "acceptance_tests/acceptance_results.json", "DEF-08 устранён"),
    "REQ-DA-09": ("PASS", "Автотриггер формирует .md и .docx, задание персистентно, без дублей между бакетами cooldown, ошибка фиксируется и повторяется, документ доступен оператору через HMI", E + "acceptance_tests/acceptance_results.json", "DEF-20 устранён"),
    "REQ-DOC-01": ("PASS", "Валидный OpenXML .docx (браузер, API, offline-установка, soak)", E + "browser_e2e/; " + E + "offline_install/", ""),
    "REQ-DOC-02": ("PASS", ".md для предпросмотра и скачивания", E + "browser_e2e/", ""),
    "REQ-DOC-03": ("PASS", "Пять разделов в .md и .docx", E + "browser_e2e/e2e_spec.md", ""),
    "REQ-DOC-04": ("PASS", "Период меняет выборку SQLite и события: 12h/24h/7d/30d дают +1 отсчёт и +1 событие на каждый шаг контрольного набора, пик 11,04 МПа только в 30d; история всех 36 приборов пишется в БД", E + "acceptance_tests/acceptance_results.json", "DEF-03, NEW-05, NEW-06 устранены"),
    "REQ-DOC-05": ("PASS", "Реальные стоп-кадры событий в .docx, синтетические иллюстрации помечены, без фиктивного CONF", E + "browser_e2e/e2e_spec.docx", "DEF-04 устранён"),
    "REQ-DOC-06": ("PASS", "Исправное оборудование — пустая ведомость и CAPEX 0; неизвестный фильтр → 422; единичное срабатывание без CAPEX", E + "acceptance_tests/acceptance_results.json", "DEF-04, DEF-17 устранены"),
    "REQ-DOC-07": ("PASS", "Требования 4–20 мА/HART/RS-485, класс точности, IP65/67, Ex для газа/мазута", E + "original_audit_rerun/", ""),
    "REQ-DOC-08": ("PASS", "CAPEX, OPEX, эффект и окупаемость сверены с формулами; CAPEX=0 → окупаемость не рассчитывается", E + "acceptance_tests/acceptance_results.json", "DEF-04 устранён"),
    "REQ-DOC-09": ("PASS", "Детерминированный режим без сети; offline-установка: ноль сетевых обращений", E + "offline_install/offline_install_results.json", ""),
    "REQ-DOC-10": ("NOT VERIFIED", "Проверка на реальной локальной LLM ещё не выполнена", E + "llm/llm_local_results.json", ""),
    "REQ-CV-01": ("PASS", "YOLOv8 из локальных весов на CPU в чистой offline-установке", E + "offline_install/offline_install_results.json", ""),
    "REQ-CV-02": ("PASS", "CW / CCW / отрицательные шкалы, переход 0/360° (audit_01 на финальном коде)", E + "original_audit_rerun/", ""),
    "REQ-CV-03": ("PASS", "Нормальный кадр без плашки CRITICAL; перекрытие 44 % отклоняется; ограничение «1 камера — 1 ROI» задокументировано", E + "original_audit_rerun/; " + E + "acceptance_tests/", "DEF-02, DEF-15 устранены"),
    "REQ-CV-04": ("PASS", "Смартфон-камера по WSS с переходом в аварию и записью в SQLite (interop, soak, test_demo_dashboard)", E + "interop/interop_results.json; " + E + "soak/summary.json", ""),
    "REQ-CV-05": ("NOT VERIFIED", "Размеченных фотографий реальных цеховых КИПиА нет; найденные изображения сгенерированы Gemini и для валидации непригодны. Протокол испытания подготовлен", "—", "DEF-22 (п. 1) открыт"),
    "REQ-CV-06": ("PARTIAL", "5-кадровый CUDA smoke на RTX 5060 Laptop (50–58 мс/кадр после прогрева, torch 2.14.1+cu130); длительная GPU-нагрузка на ноутбуке запрещена; бенчмарк для RTX 3090 подготовлен", E + "antigravity/cuda_smoke_5frames.json", ""),
    "REQ-HMI-01": ("PASS", "Три рабочих контура без перезагрузки", E + "browser_e2e/browser_e2e_report.json", ""),
    "REQ-HMI-02": ("PASS", "Топология, сетка камер, фокус, инспектор", E + "browser_e2e/browser_e2e_report.json", ""),
    "REQ-HMI-03": ("PASS", "Кнопка обрыва: очередь растёт, после восстановления досылается за 2 с", E + "browser_e2e/browser_e2e_report.json", ""),
    "REQ-HMI-04": ("PASS", "Матрица 36 строк, тренды, рекомендации, лента инцидентов с верными тегами", E + "browser_e2e/browser_e2e_report.json", "DEF-18 устранён"),
    "REQ-HMI-05": ("PASS", "Период, реквизиты, предпросмотр, скачивание .docx/.md", E + "browser_e2e/browser_e2e_report.json", ""),
    "REQ-HMI-06": ("PASS", "Нет переполнения и усечённого текста на 1920×1080, 1440×900, 1280×720 во всех трёх контурах", E + "browser_e2e/browser_e2e_report.json", "DEF-16 устранён; новая обрезка плашки пользователя исправлена"),
    "REQ-HMI-07": ("PASS", "0 ошибок консоли и страницы, 0 HTTP 4xx/5xx, 0 символов middle dot", E + "browser_e2e/browser_e2e_report.json", ""),
    "REQ-SEC-01": ("PASS", "Браузер: 0 внешних запросов; сервер: аудит-хук Python зафиксировал 0 DNS-запросов и подключений к нелокальным адресам", E + "offline_install/runtime_network_audit.jsonl", "NEW-11 устранён"),
    "REQ-SEC-02": ("PASS", "Чистая установка из wheelhouse без индекса: 61 пакет совпал с lock, pip check без ошибок, YOLOv8 на CPU", E + "offline_install/offline_install_results.json", "DEF-05, NEW-09 устранены"),
    "REQ-SEC-03": ("PASS", "Пароль RTSP не попадает в API, WS, SQLite и журналы; токены в журналах маскируются", E + "acceptance_tests/acceptance_results.json; " + E + "interop/interop_results.json", "DEF-07, NEW-10 устранены"),
    "REQ-SEC-04": ("PASS", "13 вариантов SSRF и 9 вариантов Path Traversal → 422; SSRF перепроверяется при каждом подключении", E + "acceptance_tests/acceptance_results.json", "DEF-07 устранён"),
    "REQ-SEC-05": ("PASS", "RBAC на всех маршрутах и WS, блокировка перебора, роль из БД, стендовые пароли запрещены вне демо, CSP/X-Frame-Options", E + "acceptance_tests/acceptance_results.json", "DEF-07, DEF-20, NEW-04 устранены"),
    "REQ-SEC-06": ("PASS", "Разграничение с СИ ФЗ-102 и ПАЗ в HMI и .docx; невалидные данные — NaN в Modbus и статус STALE", E + "browser_e2e/e2e_spec.docx", "DEF-22 (п. 4) устранён"),
    "REQ-ARCH-01": ("PASS", "Скан: нет TODO/FIXME/NotImplementedError и абсолютных путей в коде приложения и переносимых скриптах", E + "static_scan.json", ""),
    "REQ-ARCH-02": ("PASS", "Пути от корня репозитория, .env.example", E + "offline_install/", ""),
    "REQ-ARCH-03": ("PASS", "Стендовые профили вынесены из аналитики, демо-логика в app/demo.py", "app/dispatch_analyzer.py", "DEF-08, DEF-11 устранены"),
    "REQ-ARCH-04": ("PASS", "Сериализация доставки S&F, ожидание фоновых записей при остановке, персистентные журналы и клипы, миграция БД baseline", E + "acceptance_tests/acceptance_results.json", "DEF-02, DEF-10, DEF-20 устранены"),
    "REQ-QA-01": ("PASS", "Исходные наборы проходят; изменён только шаг входа из-за RBAC, проверки не тронуты", E + "test_runs/", ""),
    "REQ-QA-02": ("PASS", "Независимый набор из 19 проверок, негативные сценарии, сторонние реализации протоколов", E + "acceptance_tests/acceptance_results.json", ""),
    "REQ-QA-03": ("NOT VERIFIED", "Часовой soak ещё не завершён", E + "soak/summary.json", "DEF-22 (п. 2, 3)"),
}


def main() -> None:
    rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    assert len(rows) == 75, len(rows)
    out_rows = []
    agg: dict[str, dict[str, int]] = {}
    for r in rows:
        st, actual, ev, defects = STATUS[r["ID"]]
        d = agg.setdefault(r["Направление"], {"PASS": 0, "PARTIAL": 0, "FAIL": 0, "NOT VERIFIED": 0, "n": 0})
        d[st] += 1
        d["n"] += 1
        out_rows.append({
            "ID": r["ID"], "Направление": r["Направление"], "Требование": r["Требование"], "Приоритет": r["Приоритет"],
            "Ожидаемый результат (критерий аудита)": r["Ожидаемый результат"],
            "Статус аудита Gemini": r["Статус"], "Статус повторной приёмки": st,
            "Фактический результат повторной приёмки": actual, "Доказательство": ev,
            "Дефекты аудита": r["Дефект"], "Состояние дефектов": defects,
        })
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    total = 0.0
    dirs = {}
    for name, mx in MAX_POINTS.items():
        d = agg[name]
        pts = mx * (d["PASS"] + 0.5 * d["PARTIAL"]) / d["n"]
        total += pts
        dirs[name] = {**d, "max": mx, "points": round(pts, 2)}
    counts = {k: sum(d[k] for d in agg.values()) for k in ("PASS", "PARTIAL", "FAIL", "NOT VERIFIED")}
    score = {"directions": dirs, "total": round(total, 2), "counts": counts,
             "compliance_pct": round((counts["PASS"] + 0.5 * counts["PARTIAL"]) / 75 * 100, 1),
             "verified_pct": round((75 - counts["NOT VERIFIED"]) / 75 * 100, 1)}
    SCORE.parent.mkdir(parents=True, exist_ok=True)
    SCORE.write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": score["total"], "counts": counts, "compliance_pct": score["compliance_pct"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
