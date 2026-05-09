from pydantic import BaseModel
import os

from backend.env import load_local_env


load_local_env()


class Settings(BaseModel):
    app_name: str = os.getenv("PAPERRADAR_APP_NAME", "PaperRadar API")
    app_env: str = os.getenv("PAPERRADAR_APP_ENV", "development")
    app_host: str = os.getenv("PAPERRADAR_APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("PAPERRADAR_APP_PORT", "8100"))
    redis_url: str = os.getenv("PAPERRADAR_REDIS_URL", "redis://127.0.0.1:6379/0")
    retrieval_queue_prefix: str = os.getenv("PAPERRADAR_RETRIEVAL_QUEUE_PREFIX", "paperradar:retrieval")
    retrieval_queue_max_size: int = int(os.getenv("PAPERRADAR_RETRIEVAL_QUEUE_MAX_SIZE", "16"))
    retrieval_job_ttl_seconds: int = int(os.getenv("PAPERRADAR_RETRIEVAL_JOB_TTL_SECONDS", "1800"))
    retrieval_max_concurrency: int = int(os.getenv("PAPERRADAR_RETRIEVAL_MAX_CONCURRENCY", "1"))
    retrieval_worker_poll_seconds: float = float(os.getenv("PAPERRADAR_RETRIEVAL_WORKER_POLL_SECONDS", "1.0"))
    retrieval_sync_wait_timeout_seconds: float = float(os.getenv("PAPERRADAR_RETRIEVAL_SYNC_WAIT_TIMEOUT_SECONDS", "120"))
    gemini_api_key: str = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    gemini_model: str = os.getenv("PAPERRADAR_GEMINI_MODEL", "gemini-3-flash-preview")
    query_type_classifier_model: str = os.getenv("PAPERRADAR_QUERY_TYPE_MODEL", "")
    auth_admin_username: str = os.getenv("PAPERRADAR_ADMIN_USERNAME", "admin")
    auth_admin_password: str = os.getenv("PAPERRADAR_ADMIN_PASSWORD", "")
    auth_cookie_name: str = os.getenv("PAPERRADAR_AUTH_COOKIE_NAME", "paperradar_session")
    auth_cookie_secure: bool = os.getenv("PAPERRADAR_AUTH_COOKIE_SECURE", "false").lower() == "true"


settings = Settings()
