# syntax=docker/dockerfile:1.7
# Build context: repo root (docker build -f backend/Dockerfile .)

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app

RUN pip install --target /deps \
      "fastapi>=0.115.0" \
      "uvicorn[standard]>=0.32.0" \
      "pydantic>=2.9.0" \
      "pydantic-settings>=2.6.0" \
      "httpx>=0.27.0" \
      "sqlalchemy[asyncio]>=2.0.36" \
      "asyncpg>=0.30.0" \
      "psycopg2-binary>=2.9.10" \
      "redis>=5.2.0" \
      "google-generativeai>=0.8.0" \
      "pyyaml>=6.0.2" \
      "python-multipart>=0.0.12" \
      "azure-identity>=1.19.0" \
      "kubernetes>=31.0.0"


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/deps \
    PATH=/deps/bin:$PATH \
    DEBUG=false \
    DEMO_MODE_ENABLED=false \
    PROMPTS_DIR=/app/prompts

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1001 app \
 && useradd  --system --uid 1001 --gid 1001 --home /app --shell /sbin/nologin app

WORKDIR /app

COPY --from=builder /deps /deps
COPY backend/app /app/app
COPY prompts    /app/prompts

RUN chown -R app:app /app
USER app

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
