"""OpenAI 이미지 생성 API 호출 테스트.

저장소 루트의 .env에 있는 OPENAI_API_KEY로 이미지 1장을 만들어
experiments/test_output/ 에 저장한다. (test_output/ 은 Git에서 제외됨)

실행:
    python experiments/test_openai_image.py
    python experiments/test_openai_image.py "다른 프롬프트"
"""

from __future__ import annotations

import base64
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path(__file__).resolve().parent / "test_output"

DEFAULT_PROMPT = "꿈속의 바닷가, 몽환적인 수채화 풍"
MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
SIZE = "1024x1024"
QUALITY = "medium"


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print(f"OPENAI_API_KEY가 없습니다. {REPO_ROOT / '.env'} 파일에 키를 넣어 주세요.")
        return 1

    prompt = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROMPT
    print(f"모델: {MODEL} / 크기: {SIZE} / 품질: {QUALITY}")
    print(f"프롬프트: {prompt}")

    client = OpenAI(api_key=api_key)
    result = client.images.generate(
        model=MODEL,
        prompt=prompt,
        size=SIZE,
        quality=QUALITY,
        n=1,
    )

    image_b64 = result.data[0].b64_json
    if not image_b64:
        print("응답에 이미지 데이터가 없습니다.")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"dream_beach_{datetime.now():%Y%m%d_%H%M%S}.png"
    out_path.write_bytes(base64.b64decode(image_b64))
    print(f"저장 완료: {out_path}")

    if result.usage:
        print(f"토큰 사용량: {result.usage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
