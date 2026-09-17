from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_name: str = "AI-фотобудка"
    admin_telegram_id: int = 0
    telegram_bot_token: str = ""
    openai_api_key: str = ""
    fal_key: str = ""
    database_url: str = "sqlite:///./photo_generation.db"
    redis_url: str = "redis://localhost:6379/0"
    media_dir: str = "./media"
    mock_mode: bool = True
    openai_image_model: str = "gpt-image-2.5-sunburst"
    fal_model_luxury: str = "fal-ai/nano-banana-2"
    fal_model_identity: str = "fal-ai/phota/edit"
    fal_model_composite: str = "fal-ai/hy-wu-edit"
    free_generations_per_day: int = 1
    paid_credits_per_pack: int = 3
    paid_pack_stars: int = 30
    max_upload_mb: int = 20
    result_ttl_hours: int = 24
    public_base_url: str = "http://localhost:8000"
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_timeout_seconds: int = 30
    worker_concurrency: int = 2
    max_queue_size: int = 500
    max_active_jobs_per_user: int = 1
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "auto"
    s3_prefix: str = "photo-generation"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
