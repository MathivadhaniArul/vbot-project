@echo off
setlocal
celery -A celery_app.celery_app worker --loglevel=INFO --pool=solo
