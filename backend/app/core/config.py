from pathlib import Path

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

    # Database & Cache (optional at initial foundation stage)
    DATABASE_URL: str = ""
    NEO4J_URI: str = ""
    NEO4J_USERNAME: str = ""
    NEO4J_PASSWORD: str = ""
    NEO4J_DATABASE: str = "neo4j"
    REDIS_URL: str = ""
    REDIS_TOKEN: str = ""

    # Google Auth (optional at initial foundation stage)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    GOOGLE_FRONTEND_URL: str = "http://localhost:3000"

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
