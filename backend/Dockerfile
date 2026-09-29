# syntax=docker/dockerfile:1.7
# ---- build stage: compile wheels -------------------------------------------------------
FROM python:3.11-slim-bookworm AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---- runtime stage ------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PORT=8000 ENVIRONMENT=production LOG_JSON=true
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /app app
WORKDIR /app
COPY --from=build /wheels /wheels
# setuptools/wheel are build-time only; removing them drops their vendored packages (flagged by Trivy)
# from the runtime image. Verified: API, Celery and Alembic run without them.
RUN pip install --no-index --find-links=/wheels /wheels/* && rm -rf /wheels \
    && pip uninstall -y setuptools wheel
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
COPY --chown=app:app scripts ./scripts
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"
# Same image runs the API (default), Celery worker/beat, and migrations (see docker-compose / Helm).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --workers ${WEB_CONCURRENCY:-2}"]
