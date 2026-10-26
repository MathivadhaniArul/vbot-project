#!/usr/bin/env bash
set -euo pipefail
celery -A celery_app.celery_app worker --loglevel=INFO --concurrency=4
