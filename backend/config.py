"""Environment-backed application configuration."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized not in {"true", "false", "1", "0", "yes", "no"}:
        raise RuntimeError(f"{name} must be a boolean")
    return normalized in {"true", "1", "yes"}


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    auth_mode: str
    session_ttl_minutes: int
    cookie_secure: bool
    cors_origins: tuple[str, ...]
    demo_admin_username: str
    initial_admin_password: str
    login_attempt_limit: int
    login_attempt_window_seconds: int
    sqlite_busy_timeout_ms: int
    max_request_bytes: int


def load_settings() -> Settings:
    environment = os.getenv("VIDYUTSETU_ENV", "development").strip().lower()
    auth_mode = os.getenv("VIDYUTSETU_AUTH_MODE", "demo").strip().lower()
    if environment not in {"development", "test", "production"}:
        raise RuntimeError("VIDYUTSETU_ENV must be development, test, or production")
    if auth_mode not in {"demo", "password", "disabled"}:
        raise RuntimeError("VIDYUTSETU_AUTH_MODE must be demo, password, or disabled")
    if environment == "production" and auth_mode == "disabled":
        raise RuntimeError("Authentication cannot be disabled in production")

    return Settings(
        environment=environment,
        database_url=os.getenv("VIDYUTSETU_DATABASE_URL", "sqlite:///./vidyutsetu.db"),
        auth_mode=auth_mode,
        session_ttl_minutes=_integer("VIDYUTSETU_SESSION_TTL_MINUTES", 480, 5, 1440),
        cookie_secure=_boolean("VIDYUTSETU_COOKIE_SECURE", environment == "production"),
        cors_origins=tuple(
            origin.strip()
            for origin in os.getenv("VIDYUTSETU_CORS_ORIGINS", "").split(",")
            if origin.strip()
        ),
        demo_admin_username=os.getenv("VIDYUTSETU_DEMO_ADMIN_USERNAME", "admin").strip(),
        initial_admin_password=os.getenv("VIDYUTSETU_INITIAL_ADMIN_PASSWORD", ""),
        login_attempt_limit=_integer("VIDYUTSETU_LOGIN_ATTEMPT_LIMIT", 5, 1, 100),
        login_attempt_window_seconds=_integer(
            "VIDYUTSETU_LOGIN_ATTEMPT_WINDOW_SECONDS", 300, 10, 86400
        ),
        sqlite_busy_timeout_ms=_integer("VIDYUTSETU_SQLITE_BUSY_TIMEOUT_MS", 5000, 100, 60000),
        max_request_bytes=_integer("VIDYUTSETU_MAX_REQUEST_BYTES", 5 * 1024 * 1024, 1024, 50 * 1024 * 1024),
    )


settings = load_settings()
