from __future__ import annotations
from celery import Celery
from .config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

celery_app = Celery("cutflow", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND, include=["app.services.jobs"])
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
)
