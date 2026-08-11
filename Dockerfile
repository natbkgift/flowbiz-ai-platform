FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY .artifacts/flowbiz_ai_core-0.2.3-py3-none-any.whl /tmp/flowbiz_ai_core-0.2.3-py3-none-any.whl
COPY pyproject.toml README.md ./
COPY apps ./apps
COPY platform_app ./platform_app
COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY deploy/start.sh /usr/local/bin/flowbiz-platform-start
# platform_app/static/operator/* is internal-only AI Operator Console assets.

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir /tmp/flowbiz_ai_core-0.2.3-py3-none-any.whl \
    && python -m pip install --no-cache-dir . \
    && rm -f /tmp/flowbiz_ai_core-0.2.3-py3-none-any.whl \
    && sed -i 's/\r$//' /usr/local/bin/flowbiz-platform-start \
    && chmod 0555 /usr/local/bin/flowbiz-platform-start \
    && groupadd --system --gid 4311 flowbiz-platform \
    && useradd --system --uid 4311 --gid 4311 --home-dir /nonexistent \
        --shell /usr/sbin/nologin flowbiz-platform

RUN mkdir -p /app/platform_data \
    && chown -R 4311:4311 /app/platform_data

USER 4311:4311

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/healthz', timeout=3).read()"]

CMD ["/usr/local/bin/flowbiz-platform-start"]
