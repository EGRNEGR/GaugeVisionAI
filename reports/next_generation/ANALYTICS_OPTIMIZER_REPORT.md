# Отчёт о реализации этапов Roadmap: Predictive Analytics и Modernization Optimizer

**Дата:** 27 ноября 2026 г.  
**Ветка разработки:** `next-gen/analytics-optimizer` (создана от завершённой SCADA-ветки `next-gen/scada-ignition`, коммит `d131d55`)  
**Изоляция:** ветки `main`, `GaugeVision-2.0`, файл `app/vision.py` и каталоги `reports/audit/`, `reports/remediation/` не изменялись.

---

## 1. Согласование контрактов с будущей многоприборной архитектурой (`app/contracts.py`)

Для бесшовной стыковки с параллельной разработкой **Multi-Gauge Vision** (несколько приборов в кадре одной камеры) введён единый контракт идентификации `InstrumentIdentity`:

- **`instrument_id`** — первичный стабильный идентификатор прибора (поддерживает и текущую модель `instrument_id == camera_id`, и многоприборную `<camera_id>#g<slot>` или независимый UUID);
- **`camera_id`** — идентификатор физической камеры (`None` для стендовой симуляции);
- **`gauge_slot`** — целочисленный 0-based слот циферблата в кадре камеры (`0` для одноприборной камеры, `0, 1, 2, …` для multi-gauge, `None` для симуляции).

В SQLite (`app/db.py`) добавлена безопасная миграция `ALTER TABLE readings ADD COLUMN instrument_id TEXT` с индексом `idx_readings_inst_ts` и унифицированным запросом `get_instrument_series()` по `COALESCE(instrument_id, camera_id)` с объединением `readings` и `instrument_readings`. Новые таблицы `instrument_passports` и `predictive_snapshots` используют `instrument_id`, `camera_id` и `gauge_slot`.

---

## 2. Predictive Analytics (`app/predictive_analytics.py`)

### Реализованные математические модели

1. **Экспоненциально-взвешенная линейная регрессия (WLS)** по фактическим временным меткам с эффективным числом степеней свободы `df_eff = n_eff − 2`, оценкой остаточной дисперсии `se_resid` и `R²_w`.
2. **Робастная оценка наклона Тейла-Сена (Theil-Sen median slope)** — при наличии одиночных выбросов (до 35 % выборки по MAD), искажающих OLS-остатки или наклон, модель автоматически переключается на робастную оценку `theil_sen_robust` с MAD-масштабированием остатков.
3. **Неопределённость прогноза (80 % и 95 % предиктивные интервалы)** — рассчитывается по точным двусторонним квантилям распределения Стьюдента `t_{df, α}` (таблица малых `df` + разложение Корниша-Фишера, без внешних зависимостей) с ростом стандартной ошибки на горизонте `h`:
   $$SE_{pred}(h) = s_e \sqrt{1 + \frac{1}{n_{eff}} + \frac{(h - \bar{x}_w)^2}{S_{xx,w}}}$$
4. **Оценка времени достижения уставок (ETA до `LL`, `L`, `H`, `HH`)** с уважением флага `lower_enabled`:
   - точечная медианная оценка `eta_median_min`;
   - пессимистичная (ранняя) и оптимистичная (поздняя) границы по пересечению 95 % ДИ численной бисекцией (`eta_early_min <= eta_median_min <= eta_late_min`);
   - вероятность пробоя уставки в пределах горизонта `H` (`breach_prob_horizon`) через хвостовую функцию `erfc`.
5. **Обнаружение аномальных трендов:**
   - двусторонний **CUSUM** (с защитой от ложных срабатываний на штатных периодических колебаниях через проверку фактического смещения медианы хвоста);
   - непараметрический **критерий Манна-Кендалла** (`S`, `Z_mk`, `p_value` с поправкой на совпадения);
   - оценка **ускорения тренда (`d²V/dt²`, `accel_z`)** по сравнению первой и второй половин окна;
   - **модифицированный Z-score (MAD)** для выбросов и **коэффициент роста волатильности (`vol_ratio`)**.
6. **Честная обработка граничных случаев:** при `< 6` точках или охвате `< 20 с` возвращается `status = "insufficient_data"`, при невалидном канале — `status = "stale_channel"` (`eta = None`, `breach_prob = 0.0`, `confidence = 0.0`).

### Математическая верификация (`tests/test_predictive_analytics.py`)

| Проверка | Показатель | Результат |
|---|---|---|
| Точный линейный тренд вверх (`+0,5 °C/мин`, `H=555`, `HH=565`) | `ETA_warn = 40,0 мин` (аналит. `40,0`), `ETA_alert = 60,0 мин` (аналит. `60,0`) | **PASS** |
| Точный линейный тренд вниз (`−0,5 °C/мин`, `L=505`, `LL=485`) + `lower_enabled=False` | `ETA_warn = 20,0 мин`, `ETA_alert = 60,0 мин`; при `lower_enabled=False` нижние уставки исключены | **PASS** |
| Монте-Карло калибровка 95 % ДИ (150 испытаний, `σ = 1,2`) | Эмпирическое покрытие **92,0 %** (цель ≥ 88 %); ширина ДИ растёт `5,978 (30 мин) → 13,374 (120 мин)` | **PASS** |
| Устойчивость Theil-Sen к 4 выбросам `+85 °C` | Восстановленный наклон **`0,3000 °C/мин`** (истина `0,3000`), метод `theil_sen_robust`, флаг `mad_outliers` | **PASS** |
| Детекторы аномалий (CUSUM / ускорение / шум / волатильность) | `CUSUM = 447,27`, `accel_z = 16,31`, стационарный шум `MK p = 0,3397` (`stable`), `vol_ratio = 13,84×` | **PASS** |
| Multi-Gauge контракт (`cam-multi-01#g0`, `#g1`) + SQLite + Modbus `3600+` | Слоты `[0, 1]`, сохранено `2` снапшота, Modbus `HR 43601` декодировал `ETA = 62,5 мин` | **PASS** |

---

## 3. Modernization Optimizer (`app/ilp_solver.py`, `app/modernization_optimizer.py`)

### Математическая постановка 0-1 ILP (Branch-and-Bound)

- **Переменные:** $x_i \in \{0, 1\}$ для каждого кандидата модернизации.
- **Целевые функции:** `weighted_utility` (нормированная взвешенная комбинация снижения риска и чистого экономического эффекта), `max_risk_reduction`, `max_net_effect`.
- **Ограничения:** бюджет CAPEX ($\sum c_i x_i \le B$), обязательные мероприятия ($x_i = 1$ с транзитивным замыканием зависимостей), исключения ($x_i = 0$), лимит числа позиций за этап ($\sum x_i \le K_{max}$), групповые квоты ($L_g \le \sum_{i \in g} x_i \le U_g$), зависимости ($x_a \le x_b$) и взаимоисключающие альтернативы (SOS1).
- **Решатель (`solve_binary_ilp`):** автономный (air-gapped) метод ветвей и границ с математически допустимой верхней границей $UB = \min(UB_{budget}, UB_{cardinality}) \ge OPT$, гарантирующей **доказанный глобальный оптимум (`optimality_gap = 0.0`)** и честную диагностику `infeasible` с точным дефицитом бюджета.
- **Реальные входные данные:** объединяет `DispatchAnalyzer`, `PredictiveAnalyzer`, инженерные паспорта `instrument_passports` (категория критичности I/II/III, `1Ex`, обязательность по предписанию) и каталог `DIGITAL_SENSOR_CATALOG`. Чисто оптические проблемы камеры (`optical_degradation`) не включаются в CAPEX замены манометров.
- **Аналитика решения:** строит **кривую Парето (Budget Frontier)** по сетке бюджетов и количественное сравнение выигрыша ILP против жадного базового алгоритма (`solve_greedy_baseline`).

### Математическая и интеграционная верификация (`tests/test_modernization_optimizer.py`)

| Проверка | Показатель | Результат |
|---|---|---|
| Сверка с полным перебором Brute-Force $2^N$ (40 случайных задач, $N = 8..13$) | **40 / 40 (100,0 %)** точное совпадение целевой функции (`gap = 0,0`), макс. время решения **`0,18 мс`** | **PASS** |
| Превосходство ILP над жадным алгоритмом и диагностика `infeasible` | `ILP = 100,0` против `Greedy = 66,0` (**`+51,52 %`**); при дефиците `status = infeasible`, `min_required = 215 000 ₽`, `deficit = 65 000 ₽` | **PASS** |
| Отделение оптики и влияние Predictive Analytics | Оптический канал исключён из CAPEX датчиков; рост прогнозного риска поднял балл риска `84,86 → 166,24` | **PASS** |
| Сквозная интеграция API + SQLite + `.md`/`.docx` | Паспорта (36), сохранение плана `#1` (`4` поз., `336 300 ₽`, покрытие риска `77,0 %`), сгенерирован валидный `.docx` (`135 152 B`) с разделом оптимизации ILP | **PASS** |

---

## 4. Системная интеграция (API, SQLite, SCADA, Spec Generator, HMI)

- **REST API (`app/main.py`):**
  - `GET /api/predictive/overview`, `GET /api/predictive/instrument/{id}`, `GET /api/predictive/history/{id}`;
  - `GET /api/passports`, `PATCH /api/passports/{id}`;
  - `POST /api/optimizer/solve`, `POST /api/optimizer/plans`, `GET /api/optimizer/plans`, `GET /api/optimizer/plans/{id}`;
  - `/api/dispatch/overview` и `/api/dispatch/instrument/{id}` обогащены блоком `predictive`;
  - `/api/specs/preview` и `/api/specs/generate` поддерживают `optimization_plan_id`, `optimization_budget_rub` и `selected_instrument_ids`, формируя разделы **5.1** (прогнозные риски) и **5.2** (оптимизация бюджета 0-1 ILP) в `.md` и `.docx`.
- **SCADA (`app/scada_gateway.py`, `docs/MODBUS_REGISTER_MAP.md`):** добавлен обратно совместимый прогнозный блок `3600 + idx*8` (до 61 прибора, адреса `3600..4087`) и системные регистры `912..915` при полном сохранении `MAX_REGISTERS = 4096`, `register_map_version = 2` и всех прежних адресов v1/v2. В Store-and-Forward/MQTT добавлено поле `predictive_imminent_codes`.
- **HMI (`static/index.html`, `static/js/console/dispatch.js`, `static/css/console.css`):** во вкладке «Диспетчеризация и ТЗ» добавлены интерактивная панель Predictive Analytics (таблица 36 приборов, переключатели окна/горизонта, Canvas-график с конусом 80 %/95 % ДИ и линиями уставок) и панель Modernization Optimizer (бюджет + пресеты, целевая функция, чекбоксы обязательности/исключений, кривая Парето, сохранение планов в SQLite, передача оптимального портфеля в конструктор ТЗ).

---

## 5. Регрессионные испытания и браузерный E2E (Playwright)

### Регрессия всех 7 тестовых наборов (CPU)

| Тестовый набор | Результат |
|---|---|
| `tests/test_predictive_analytics.py` | **PASS (5/5)** |
| `tests/test_modernization_optimizer.py` | **PASS (4/4)** |
| `tests/test_modbus_register_map.py` | **PASS (2/2)** |
| `tests/test_demo_dashboard.py` | **PASS** |
| `tests/test_tracks_e2e.py` | **PASS** (`docx = 133 919 B`, `HR40901 = 36`) |
| `tests/test_remediation_full.py` | **PASS (8/8)** |
| `tests/test_acceptance_independent.py` | **PASS (21/21)** |

### Браузерный E2E в реальном Chromium (`reports/next_generation/evidence/analytics_optimizer/e2e_browser_results.json`)

| Сценарий E2E | Фактический результат | Скриншот |
|---|---|---|
| Вход инженером через UI (`engineer`) | `engineer (Инженер)`, `0` ошибок консоли и страницы | — |
| Панель Predictive Analytics + смена горизонта `60 → 120 мин` | `36` строк, отрисован Canvas-конус ДИ (`2985` нефоновых точек), `0` средних точек `·` в UI | `e2e_01_predictive_panel_1920x1080.png` |
| Оптимизатор 0-1 ILP (`350 000 ₽`) + сохранение плана в SQLite | `OPTIMAL (gap 0,00%, 0,0 мс)`, `4 из 7`, `336,3 т.₽ (96 %)`, покрытие риска `75,4 %`, Парето Canvas, план сохранён | `e2e_02_optimizer_optimal_1920x1080.png` |
| Несовместимый бюджет (`50 000 ₽`) при обязательной позиции | `INFEASIBLE (дефицит бюджета)`, красный баннер с дефицитом `36 640 ₽` | `e2e_03_optimizer_infeasible_1920x1080.png` |
| Передача оптимального плана в конструктор ТЗ и выгрузка `.docx` | Активен фильтр ILP, в предпросмотре присутствует раздел оптимизации, скачан `.docx` (`132 336 B`) | `e2e_04_spec_from_optimal_plan_1920x1080.png` |
| Адаптивность на экране `1280×720` | Горизонтальный overflow `0 px` | `e2e_05_analytics_optimizer_1280x720.png` |
