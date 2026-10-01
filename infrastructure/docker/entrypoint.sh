#!/bin/sh
# Loads generated installation secrets (see isocline/core/bootstrap_secrets.py) for every variable that is
# not already set to a non-empty value, then runs the container command. Values from .env always win.
set -eu
f="${ISOCLINE_SECRETS_FILE:-}"
if [ -n "$f" ] && [ -r "$f" ]; then
  # Split on the FIRST '=' only: base64 values end in '=' padding, which `IFS='=' read` would strip.
  while IFS= read -r line; do
    case "$line" in ''|\#*) continue ;; esac
    key="${line%%=*}"
    value="${line#*=}"
    case "$key" in *[!A-Za-z0-9_]*) continue ;; esac
    eval "current=\${$key:-}"
    if [ -z "$current" ]; then export "$key=$value"; fi
  done < "$f"
fi
exec "$@"
