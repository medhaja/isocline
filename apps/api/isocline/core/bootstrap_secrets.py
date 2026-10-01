"""First-start secret generation for Docker Compose (``python -m isocline.core.bootstrap_secrets PATH``).

Writes random values for the installation's secrets to PATH (mode 0600) if the file does not exist yet, so that
``cp .env.example .env && docker compose up`` needs no manual key generation and never runs with a secret that is
published in the repository. Values set explicitly in the environment (.env) always take precedence: the container
entrypoint (infrastructure/docker/entrypoint.sh) only fills variables that are empty.

The file lives in the ``secrets`` volume. Deleting that volume makes existing encrypted credentials unreadable and
signs everyone out -- back it up with the database.
"""
from __future__ import annotations

import base64
import os
import secrets
import sys


def generate() -> dict[str, str]:
    sandbox = secrets.token_urlsafe(32)
    return {
        "ISOCLINE_SECRET_KEY": secrets.token_urlsafe(48),
        "ISOCLINE_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),  # Fernet key
        "ISOCLINE_SANDBOX_TOKEN": sandbox,
        "SANDBOX_TOKEN": sandbox,  # the sandbox service reads the same token under this name
    }


def main(path: str) -> int:
    if os.path.exists(path):
        print(f"secrets: {path} already exists, keeping it")
        return 0
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        for k, v in generate().items():
            f.write(f"{k}={v}\n")
    print(f"secrets: generated {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/secrets/secrets.env"))
