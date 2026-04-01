#!/usr/bin/env bash
set -euo pipefail

export CELERY_TASK_ALWAYS_EAGER="${CELERY_TASK_ALWAYS_EAGER:-true}"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

