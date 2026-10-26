#!/usr/bin/env bash
set -euo pipefail
celery -A celery_app.celery_app beat --loglevel=INFO
