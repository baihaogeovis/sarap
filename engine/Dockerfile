# SARAP processing engine, mock-capable image.
# v1 does not download Sentinel-1 and does not install SNAP.
# Real mode (SARAP_ENGINE_MODE=snap) fails with GPT_NOT_FOUND when gpt is absent.
# The process does not write platform business tables; it only calls the platform HTTP ingest API.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SARAP_ENGINE_MODE=mock \
    SARAP_ENGINE_INGEST_MODE=http \
    SARAP_ENGINE_HOST=0.0.0.0 \
    SARAP_ENGINE_PORT=8081 \
    SARAP_ENGINE_WORKER=true \
    SARAP_ENGINE_WORK_DIR=/data/engine-work \
    SARAP_ENGINE_DB_URL=sqlite:////data/engine-work/engine-jobs.sqlite

COPY engine /app
RUN pip install --no-cache-dir . \
    && mkdir -p /data/engine-work

EXPOSE 8081
CMD ["python", "-m", "sarap_engine.main", "--host", "0.0.0.0", "--port", "8081"]
