@echo off
setlocal
celery -A celery_app.celery_app beat --loglevel=INFO
