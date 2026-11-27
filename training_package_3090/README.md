# Автономный пакет обучения детекторов и моделей позы на Linux RTX 3090 (24 ГБ)

Данный пакет предназначен для воспроизводимого GPU-обучения полнокадровых моделей обнаружения, ключевых точек и сегментации приборов (`YOLOv8n`, `YOLO26n`, `YOLO26s`, `YOLO26s-p2`, `YOLO26s-pose`, `YOLO26s-seg`, `RF-DETR Nano / Small`) на выделенной машине с NVIDIA RTX 3090 24 ГБ.

> **Аппаратная безопасность:** обучение полнокадровых моделей **не запускается** на ноутбуке с RTX 5060 Laptop 8 ГБ из-за зафиксированных аппаратных сбоев WHEA/PCIe.

## 1. Требования к окружению (Linux RTX 3090)

- Python 3.11 / 3.12, CUDA 12.x / 13.x, PyTorch ≥ 2.4
- `ultralytics==8.4.183` (для семейства YOLO — лицензия AGPL-3.0)
- `rfdetr` (для RF-DETR Nano/Small — лицензия Apache 2.0, коммерчески чистый вариант)
- `onnx`, `onnxruntime-gpu` (или `onnxruntime` для CPU-проверки)

## 2. Порядок запуска

```bash
# 1. Экспорт датасета (TRAIN = MeterFL M2+M3 + синтетика; VAL = MeterFL M5 + синтетика)
python training_package_3090/train_all_3090.py --stage export \
  --manifest reports/cv_next_gen/evidence/dataset_manifest.json \
  --meterfl /data/meterfl --out /data/gv31_datasets --n-synth 4000 --seed 42

# 2. Обучение и сравнение всех архитектур (поддерживает --resume)
python training_package_3090/train_all_3090.py --stage train \
  --data-dir /data/gv31_datasets --out /data/gv31_runs --device 0 --epochs 80 --patience 20

# 3. Экспорт победителей в ONNX и генерация SHA-256 для models/registry.json
python training_package_3090/train_all_3090.py --stage export_onnx \
  --runs-dir /data/gv31_runs --out /data/gv31_exported
```

## 3. Перенос весов обратно в GaugeVision

1. Скопируйте экспортированные файлы `.onnx` / `.pt` в директорию `models/` репозитория GaugeVision.
2. Зарегистрируйте SHA-256, лицензию и входное разрешение в `models/registry.json`.
3. Выполните независимую валидацию на `LOCKED_FINAL_TEST` (`python -m cv_next_gen.eval_all --profile balanced`).
