"""Application settings. All values come from the environment; nothing secret is hardcoded."""
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ISOCLINE_", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+asyncpg://isocline:isocline@postgres:5432/isocline"
    redis_url: str = "redis://redis:6379/0"
    # JWT signing secret and Fernet key for the secrets vault. Must be overridden in production.
    secret_key: str = Field(default="dev-only-change-me-dev-only-change-me")
    encryption_key: str = Field(default="")  # urlsafe base64 32-byte Fernet key
    session_ttl_minutes: int = 60 * 24
    cookie_secure: bool = False
    public_base_url: str = "http://localhost:3000"
    cors_origins: list[str] = ["http://localhost:3000"]

    sandbox_url: str = "http://python-sandbox:8100"
    sandbox_token: str = "dev-sandbox-token"

    storage_backend: str = "local"  # local | s3
    storage_local_path: str = "/data/uploads"
    sandbox_uid_base: int = 200000  # per-workspace unprivileged host uids for the terminal sandbox
    browser_headless: bool = True
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    max_upload_mb: int = 25

    # Web search provider used by the Web Search tool: tavily | brave | searxng | auto (key if configured, else searxng)
    search_provider: str = "searxng"
    searxng_url: str = "http://searxng:8080"

    # Embeddings for RAG: openai_compatible | ollama | hashing (hashing = local-dev lexical fallback)
    embedding_provider: str = "hashing"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str | None = None
    embedding_dim: int = 1536

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "Isocline <no-reply@isocline.local>"
    require_email_verification: bool = False
    # Self-hosted sign-up policy. The first account on an installation can always register and becomes its admin.
    # After that, registration is closed unless allow_signup is true (provider keys set in the environment are
    # shared by every account on the installation, so open sign-up on an exposed server would share them).
    allow_signup: bool = False
    # Optional headless bootstrap: create this admin account on startup if no account exists yet.
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # Server-enforced ceilings. Workflow settings are clamped to these.
    ceiling_runtime_seconds: int = 3600
    ceiling_llm_calls: int = 500
    ceiling_tool_calls: int = 1000
    ceiling_loop_iterations: int = 100
    ceiling_retries: int = 5
    ceiling_parallel_nodes: int = 32
    ceiling_cost_usd: float = 100.0
    ceiling_tokens: int = 5_000_000

    worker_heartbeat_seconds: int = 10
    worker_stale_seconds: int = 60

    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10

    allow_private_network_hosts: list[str] = []  # admin-allowed hosts for the HTTP tool
    enable_test_provider: bool = True
    # DEVELOPMENT ONLY: execute runs/ingestion/evaluations inside the API process instead of Celery.
    # No crash recovery or horizontal scaling. Never enable in production.
    inline_worker: bool = False  # exposes the "local_test" provider; disable in production

    # Deployment mode. "server" is the Docker Compose stack (PostgreSQL + Redis + Celery). "desktop" is the single-process
    # Windows/macOS/Linux app: SQLite, in-process workers and scheduler, and the static web UI served by the API.
    # The desktop launcher (isocline.desktop.launcher) sets this and the paths below; it is not meant for servers.
    # Current model prices (see isocline.services.model_prices). Empty disables fetching (air-gapped installs).
    model_prices_url: str = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
    model_prices_refresh_hours: int = 24

    mode: str = "server"  # server | desktop
    desktop_concurrency: int = 4  # parallel workflow runs/ingestions in desktop mode
    ui_dir: str | None = None  # directory with the exported web UI (desktop mode serves it at /)

    @property
    def desktop(self) -> bool:
        return self.mode == "desktop"

    @property
    def in_process_worker(self) -> bool:
        """Runs, ingestion and evaluations execute inside the API process (desktop mode, or the dev inline worker)."""
        return self.desktop or self.inline_worker


@lru_cache
def get_settings() -> Settings:
    return Settings()
