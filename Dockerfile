# GaugeVision AI — CPU-образ для закрытого контура (Python 3.12, Linux)
#
# Автономная сборка из локального wheelhouse под Linux (собирается на машине с доступом к PyPI):
#   powershell -File scripts/prepare_offline_bundle.ps1 -Platform manylinux_2_28_x86_64
#   docker build --build-arg OFFLINE_WHEELS=1 -t gaugevision-ai:offline .
# Сборка с доступом к PyPI и индексу PyTorch CPU (каталог wheels/ должен существовать, может быть пустым):
#   mkdir wheels && docker build -t gaugevision-ai:latest .
# Запуск:
#   docker run -d -p 8443:8443 -p 15020:15020 -v ./data:/app/data --env-file .env gaugevision-ai:offline

FROM python:3.12-slim

ARG OFFLINE_WHEELS=0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GAUGEVISION_DEVICE=cpu \
    GAUGEVISION_HOST=0.0.0.0 \
    GAUGEVISION_PORT=8443 \
    GAUGEVISION_AUTH_REQUIRED=1 \
    GAUGEVISION_MODBUS_HOST=0.0.0.0 \
    GAUGEVISION_MODBUS_PORT=15020 \
    YOLO_OFFLINE=1 \
    CUDA_VISIBLE_DEVICES=""

WORKDIR /app

# Системные библиотеки OpenCV (ultralytics тянет opencv-python с зависимостью от libGL)
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.lock ./
COPY wheels/ ./wheels/

RUN if [ "$OFFLINE_WHEELS" = "1" ]; then \
        pip install --no-cache-dir --no-index --find-links=./wheels -r requirements.lock; \
    else \
        pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
            --extra-index-url https://pypi.org/simple -r requirements.lock; \
    fi && pip check && rm -rf ./wheels

COPY app ./app
COPY static ./static
COPY models ./models
COPY run.py ./run.py

RUN mkdir -p /app/data/videos /app/data/incidents /app/data/auto_specs /app/certs \
    && useradd -m -u 10001 gaugevision \
    && chown -R gaugevision:gaugevision /app

USER gaugevision

EXPOSE 8443 15020

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import ssl, urllib.request; urllib.request.urlopen('https://127.0.0.1:8443/api/health', context=ssl._create_unverified_context(), timeout=3)" || exit 1

CMD ["python", "-B", "run.py", "--host", "0.0.0.0", "--port", "8443", "--device", "cpu"]
