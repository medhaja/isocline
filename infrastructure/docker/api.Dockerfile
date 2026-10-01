# API + Celery worker image (same code; the command decides the role).
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && useradd -u 10001 -m isocline && mkdir -p /data/uploads && chown isocline /data/uploads
COPY apps/api/requirements.txt .
RUN pip install -r requirements.txt
COPY apps/api/ /app/
COPY infrastructure/docker/entrypoint.sh /usr/local/bin/isocline-entrypoint
RUN chmod 0755 /usr/local/bin/isocline-entrypoint && mkdir -p /secrets && chown isocline /secrets
USER isocline
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD curl -fsS http://localhost:8000/healthz || exit 1
ENTRYPOINT ["isocline-entrypoint"]
CMD ["sh", "-c", "alembic upgrade head && uvicorn isocline.main:app --host 0.0.0.0 --port 8000 --proxy-headers --workers ${API_WORKERS:-2}"]
