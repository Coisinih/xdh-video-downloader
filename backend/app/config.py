from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VIDNEST_")
    download_dir: Path = Path("/tmp/vidnest-downloads")
    ttl_seconds: int = 7200
    inspection_timeout_seconds: int = 45
    download_timeout_seconds: int = 1800
    max_file_size_mb: int = 2048
    max_concurrent_downloads: int = 2
    allowed_hosts: str = ""

    @property
    def allowlist(self) -> set[str]:
        return {value.strip().lower() for value in self.allowed_hosts.split(",") if value.strip()}


settings = Settings()
