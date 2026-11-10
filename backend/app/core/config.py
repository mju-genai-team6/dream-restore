from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 저장소 루트의 .env를 읽는다 (backend/에서 실행하는 경우 ../.env)
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_env: str = "local"
    database_url: str = "postgresql+psycopg://dream:dream@localhost:5432/dream"
    storage_root: str = "../storage"
    cors_origins: str = "http://localhost:3000"

    openai_api_key: str = ""
    image_api_key: str = ""
    tts_api_key: str = ""

    # app/llm (D): 모델 이름은 .env에서 바꿀 수 있음
    llm_model: str = "gpt-4o-mini"
    stt_model: str = "whisper-1"
    llm_timeout_seconds: int = 60

    image_max_concurrency: int = 3
    job_timeout_seconds: int = 300
    audio_max_mb: int = 25

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @cached_property
    def storage_path(self) -> Path:
        return Path(self.storage_root).resolve()


settings = Settings()
