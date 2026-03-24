FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY platform_app ./platform_app

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN mkdir -p /app/platform_data

EXPOSE 8100

CMD ["uvicorn", "apps.platform_api.main:app", "--host", "0.0.0.0", "--port", "8100"]
