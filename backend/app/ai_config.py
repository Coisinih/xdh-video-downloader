from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AiSettings(BaseSettings):
    """Configuration isolated from the existing download settings."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_prefix="VIDNEST_",
    )

    ai_work_dir: Path = Path("/tmp/vidnest-ai")
    ai_ttl_seconds: int = 7200
    ai_subtitle_timeout_seconds: int = 60
    ai_max_subtitle_bytes: int = 4 * 1024 * 1024
    ai_max_transcript_chars: int = 160_000
    ai_chunk_chars: int = 24_000
    ai_max_concurrent_tasks: int = 1
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_timeout_seconds: int = 90
    deepseek_max_tokens: int = 4_096


ai_settings = AiSettings()
