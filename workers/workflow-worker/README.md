# Workflow worker

The worker runs the same Python package as the API (`apps/api/isocline`) with a different command:

```bash
celery -A isocline.worker.celery_app worker -Q runs,ingest --concurrency 4   # executes runs, evaluations, ingestion
celery -A isocline.worker.celery_app beat                                   # re-queues runs whose worker stopped heart-beating
```

Tasks are `acks_late`, so a run whose worker dies is redelivered; the executor claims runs atomically,
reuses completed node outputs on resume, and fails a run with `worker_lost` after 3 recovery attempts.
See `infrastructure/docker/api.Dockerfile` and the `worker` / `beat` services in `docker-compose.yml`.
