# Sandbox control service. It launches one disposable container per execution via the Docker CLI.
# The CLI is copied from Docker's official image (static binary, no daemon). Debian's `docker.io` package
# is not used: with --no-install-recommends newer Debian releases do not install the `docker` binary, which made
# every execution fail with "FileNotFoundError: [Errno 2] No such file or directory".
FROM docker:27-cli AS dockercli

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
RUN docker --version
WORKDIR /app
COPY workers/python-sandbox/requirements.txt .
RUN pip install -r requirements.txt
COPY workers/python-sandbox/app.py workers/python-sandbox/harness.py ./
COPY infrastructure/docker/entrypoint.sh /usr/local/bin/isocline-entrypoint
RUN chmod 0755 /usr/local/bin/isocline-entrypoint
ENTRYPOINT ["isocline-entrypoint"]
EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 CMD curl -fsS http://127.0.0.1:8100/healthz || exit 1
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
