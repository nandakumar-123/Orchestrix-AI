from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and configuration with environment variable loading."""

    # Application configuration
    APP_NAME: str = "Orchestrix AI"
    APP_ENV: str = "development"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # GitHub App configuration (optional at initial foundation stage)
    GITHUB_APP_ID: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_PRIVATE_KEY_PATH: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""
    GITHUB_APP_NAME: str = ""
    GITHUB_APP_SLUG: str = ""
    GITHUB_APP_URL: str = ""
    GITHUB_REPOSITORY_URL: str = ""

    # Model & AI Providers (optional at initial foundation stage)
    GEMINI_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    MISTRAL_MODEL: str = "mistral-large-latest"
    MISTRAL_API_BASE_URL: str = "https://api.mistral.ai/v1"

    # Cloud & Infrastructure (optional at initial foundation stage)
    GOOGLE_CLOUD_PROJECT_NAME: str = ""
    GOOGLE_CLOUD_PROJECT_RESOURCE: str = ""
    GOOGLE_CLOUD_PROJECT_NUMBER: str = ""

    # Database & Cache
    DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 300
    DB_ECHO: bool = False

    NEO4J_URI: str = ""
    NEO4J_USERNAME: str = ""
    NEO4J_PASSWORD: str = ""
    NEO4J_DATABASE: str = "neo4j"
    REDIS_URL: str = ""
    REDIS_TOKEN: str = ""

    # Google Auth & Session Security
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"
    GOOGLE_FRONTEND_URL: str = "http://localhost:3000"
    SESSION_SECRET_KEY: str = "default_insecure_dev_secret_change_in_production"
    SESSION_TTL_SECONDS: int = 60 * 60 * 24 * 7  # 7 days
    FRONTEND_ORIGIN: str = "http://localhost:3000"
    CSRF_COOKIE_NAME: str = "orchestrix_csrf"
    OAUTH_TRX_COOKIE_NAME: str = "orchestrix_oauth_trx"

    @property
    def allowed_origins(self) -> set[str]:
        """Return normalized set of allowed frontend origins without trailing slashes."""
        origins = {orig.rstrip("/") for orig in self.CORS_ORIGINS if orig}
        if self.FRONTEND_ORIGIN:
            origins.add(self.FRONTEND_ORIGIN.rstrip("/"))
        if self.GOOGLE_FRONTEND_URL:
            origins.add(self.GOOGLE_FRONTEND_URL.rstrip("/"))
        return origins

    @property
    def async_database_url(self) -> str:
        """
        Return an asyncpg-compatible database URL.

        Converts libpq parameters (e.g. sslmode=require, channel_binding=require)
        to clean asyncpg equivalents (ssl=require) without unrecognized keyword arguments.
        """
        raw_url = self.DATABASE_URL.strip()
        if not raw_url:
            return ""

        # Parse components
        split_url = urlsplit(raw_url)
        scheme = split_url.scheme

        if scheme in ("postgres", "postgresql"):
            new_scheme = "postgresql+asyncpg"
        elif scheme == "":
            new_scheme = "postgresql+asyncpg"
        else:
            new_scheme = scheme

        # Sanitize query parameters for asyncpg compatibility
        query_params = dict(parse_qsl(split_url.query))
        cleaned_params: dict[str, str] = {}

        for k, v in query_params.items():
            # asyncpg does not accept channel_binding
            if k == "channel_binding":
                continue
            # convert sslmode to ssl
            if k == "sslmode":
                cleaned_params["ssl"] = v
            else:
                cleaned_params[k] = v

        new_query = urlencode(cleaned_params)

        return urlunsplit(
            (
                new_scheme,
                split_url.netloc,
                split_url.path,
                new_query,
                split_url.fragment,
            )
        )

    @property
    def sync_database_url(self) -> str:
        """Return a synchronous postgresql:// URL for Alembic migration tooling."""
        raw_url = self.DATABASE_URL.strip()
        if not raw_url:
            return ""

        split_url = urlsplit(raw_url)
        scheme = split_url.scheme

        if scheme in ("postgres", "postgresql+asyncpg"):
            new_scheme = "postgresql"
        else:
            new_scheme = scheme

        return urlunsplit(
            (
                new_scheme,
                split_url.netloc,
                split_url.path,
                split_url.query,
                split_url.fragment,
            )
        )

    model_config = SettingsConfigDict(
        # Load .env from backend directory or workspace root directory if present
        env_file=(
            Path(__file__).resolve().parent.parent.parent / ".env",
            Path(__file__).resolve().parent.parent.parent.parent / ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
