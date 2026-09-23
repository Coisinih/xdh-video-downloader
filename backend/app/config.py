from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_prefix="VIDNEST_",
        extra="ignore",
    )
    download_dir: Path = Path("/tmp/vidnest-downloads")
    ttl_seconds: int = 7200
    inspection_timeout_seconds: int = 45
    download_timeout_seconds: int = 1800
    max_file_size_mb: int = 2048
    max_concurrent_downloads: int = 2
    allowed_hosts: str = ""
    database_path: Path = Path("/tmp/vidnest.db")
    session_ttl_seconds: int = 30 * 24 * 60 * 60
    session_cookie_secure: bool = False
    frontend_url: str = "http://localhost:8080"
    # 已废弃：2026-09 起登录用户（含免费用户）下载不限次数，仅保留字段兼容旧配置
    free_daily_downloads: int = 5
    # 非 VIP 用户每日可用的 AI 总结次数
    free_daily_ai_summaries: int = 3
    free_max_height: int = 720
    batch_max_items: int = 10
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_one_time_price_id: str = ""
    stripe_subscription_price_id: str = ""
    stripe_amount_cents: int = 990
    stripe_currency: str = "cny"
    support_email: str = "senwei0521@gmail.com"

    @property
    def allowlist(self) -> set[str]:
        return {value.strip().lower() for value in self.allowed_hosts.split(",") if value.strip()}


settings = Settings()
