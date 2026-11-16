from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SARAP_", env_file=".env", extra="ignore")

    env: str = "dev"
    secret_key: str = "change-me-dev-only"
    access_token_minutes: int = 60
    refresh_token_days: int = 7
    database_url: str = "sqlite:///./sarap.db"
    engine_url: str = "http://localhost:8081"
    engine_token: str = "dev-internal-token"
    internal_token: str = "dev-internal-token"
    cors_origins: str = "http://localhost:5173"
    seed_on_startup: bool = True
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "sarap"
    s3_secret_key: str = "sarap-dev-secret"
    s3_bucket: str = "sarap"
    s3_region: str = "us-east-1"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
