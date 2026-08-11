#!/bin/sh
set -eu

alembic upgrade head
exec uvicorn apps.platform_api.main:app --host 0.0.0.0 --port 8100
