"""이미지 생성 설정 (E2 전용).

공용 app/core/config.py는 건드리지 않고, 같은 .env 파일에서 이미지 관련 값만 읽는다.
.env에 값이 없으면 아래 기본값을 쓴다.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class ImageSettings(BaseSettings):
    # 저장소 루트의 .env를 읽는다 (backend/에서 실행하는 경우 ../.env)
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    openai_image_model: str = "gpt-image-2"
    image_size: str = "1536x1024"  # 가로형. 16:9 영상에 넣을 때 여백이 가장 적음
    image_quality: str = "medium"
    image_max_retries: int = 2  # 시간 초과·일시적 오류일 때 자동 재시도 횟수


image_settings = ImageSettings()
