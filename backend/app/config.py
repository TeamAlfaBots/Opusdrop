from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "development"
    turso_database_url: str = "file:local.db"
    turso_auth_token: str = ""
    public_base_url: str = ""
    max_file_size: int = 4_194_304  # Vercel functions cap request/response bodies at ~4.5 MB
    max_concurrent_uploads: int = 3
    upload_rate_limit: str = "20/hour"
    download_rate_limit: str = "300/hour"
    allowed_origins: str = "http://localhost:3000,http://localhost:8000"
    log_level: str = "INFO"
    database_timeout: float = 15.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def max_file_mb(self): return round(self.max_file_size / 1_048_576, 1)

    @property
    def origins(self): return [x.strip() for x in self.allowed_origins.split(",") if x.strip()]

@lru_cache
def get_settings(): return Settings()
