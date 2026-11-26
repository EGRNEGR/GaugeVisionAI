# GaugeVision AI — Air-Gapped CPU Container Image (Python 3.12)
# Сборка в закрытом контуре с предварительно собранным каталогом wheels/:
#   docker build --build-arg OFFLINE_WHEELS=1 -t gaugevision-ai:offline .
# Обычная сборка:
#   docker build -t gaugevision-ai:latest .

FROM python:3.12-slim

ARG OFFLINE_WHEELS=0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GAUGEVISION_DEVICE=cpu \
    GAUGEVISION_HOST=0.0.0.0 \
    GAUGEVISION_PORT=8000 \
    GAUGEVISION_AUTH_REQUIRED=1 \
    CUDA_VISIBLE_DEVICES=""

WORKDIR /app

# Минимальные системные библиотеки для headless OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.lock ./
COPY wheels ./wheels

RUN if [ "$OFFLINE_WHEELS" = "1" ] && [ -d "./wheels" ] && [ "$(ls -A ./wheels 2>/dev/null)" ]; then \
        pip install --no-cache-dir --no-index --find-links=./wheels -r requirements.lock; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY app ./app
COPY static ./static
COPY models ./models
COPY run.py ./run.py

RUN mkdir -p /app/data/videos /app/data/incidents /app/data/auto_specs /app/certs \
    && useradd -m -u 10001 gaugevision \
    && chown -R gaugevision:gaugevision /app

USER gaugevision

EXPOSE 8000 5020

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, ssl; ctx=ssl._create_unverified_context(); urllib.request.urlopen('https://127.0.0.1:8000/api/meta', context=ctx, timeout=3)" || exit 1

CMD ["python", "-B", "run.py", "--host", "0.0.0.0", "--port", "8000", "--device", "cpu"]
