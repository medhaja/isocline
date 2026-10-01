"""Celery application.

Queues (a worker must consume all three; see WORKER_QUEUES and docker-compose.yml):
  runs         workflow execution and evaluations
  ingest       knowledge-base document ingestion
  maintenance  periodic beat tasks: stale-run sweeper, durable-wait processor, schedule triggers, drift detection

Every task is routed explicitly and the default queue is "maintenance", so no task can land in a queue nobody consumes.
Beat only enqueues work recorded in PostgreSQL, so restarting any component loses nothing."""
from celery import Celery

from isocline.core.config import get_settings

s = get_settings()
WORKER_QUEUES = ("runs", "ingest", "maintenance")
celery = Celery("isocline", broker=s.redis_url, backend=s.redis_url, include=["isocline.worker.tasks"])
celery.conf.update(
    task_acks_late=True,  # a task is re-delivered if the worker dies mid-run
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_default_queue="maintenance",
    task_routes={"isocline.worker.tasks.execute_run": {"queue": "runs"},
                 "isocline.worker.tasks.run_evaluation": {"queue": "runs"},
                 "isocline.worker.tasks.ingest_document": {"queue": "ingest"},
                 "isocline.worker.tasks.sweep_stale_runs": {"queue": "maintenance"},
                 "isocline.worker.tasks.process_waits": {"queue": "maintenance"},
                 "isocline.worker.tasks.fire_schedules": {"queue": "maintenance"},
                 "isocline.worker.tasks.detect_drift": {"queue": "maintenance"}},
    broker_transport_options={"visibility_timeout": 3900},
    beat_schedule={"sweep-stale-runs": {"task": "isocline.worker.tasks.sweep_stale_runs", "schedule": 30.0},
                   "process-waits": {"task": "isocline.worker.tasks.process_waits", "schedule": 5.0},
                   "fire-schedules": {"task": "isocline.worker.tasks.fire_schedules", "schedule": 20.0},
                   "detect-drift": {"task": "isocline.worker.tasks.detect_drift", "schedule": 3600.0}},
    timezone="UTC",
)
