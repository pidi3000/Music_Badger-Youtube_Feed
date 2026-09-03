from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """App-wide configuration sourced from environment variables.

    These are deploy-time settings (secrets, DB location, sync cadence).
    User-editable behaviour (fetch method, retention thresholds, etc.)
    lives in the `Settings` DB row instead — see app.models.AppSettings.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Shared secret gating the whole app (single-user access, see
    # PROJECT_OUTLINE.md §2 "App access"). Used to seed AppSettings on
    # first boot; changing it later requires updating AppSettings directly.
    app_access_secret: str = "change-me"

    # Symmetric key (Fernet, base64 urlsafe 32 bytes) used to encrypt
    # ApiKey.key_value and stored YouTube OAuth tokens at rest.
    # INSECURE dev-only fallback (a syntactically valid Fernet key so the
    # app boots out of the box). Always set a real ENCRYPTION_KEY in any
    # deployment that stores real secrets.
    encryption_key: str = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="

    # Key used to sign the httpOnly session cookie (itsdangerous).
    session_secret: str = "change-me-too"
    session_cookie_name: str = "music_badger_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 30  # 30 days

    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    # How often the scheduler runs the subscription/upload sync.
    sync_interval_minutes: int = 30
    # How often the backfill queue worker ticks.
    backfill_worker_interval_seconds: int = 60

    # YouTube OAuth client, configured once real credentials exist.
    youtube_oauth_client_id: str | None = None
    youtube_oauth_client_secret: str | None = None
    youtube_oauth_redirect_uri: str = "http://localhost:8000/api/youtube/auth/callback"

    # Where the built frontend's static files live (mounted by main.py).
    static_dir: str = "./static"

    cors_allow_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_config() -> Config:
    return Config()
