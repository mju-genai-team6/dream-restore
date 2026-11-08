# app/llm — 인터뷰·장면 모듈 (정은수)

STT, 요소 추출, 되묻기 질문, 장면 분할, 이미지 프롬프트, 수정 해석.

- `prompts/`: 프롬프트 파일 (코드에 직접 쓰지 않음). 변경 내용은 `prompts/CHANGELOG.md`에 기록
- `schemas.py`: LLM 출력 Pydantic 스키마. 예시 JSON은 `docs/schemas/examples/`에 공유

서버에서 연결할 함수 (이름은 협의 후 확정)

| 함수 | 시점 | 비고 |
| --- | --- | --- |
| `transcribe(audio_path) -> str` | 11/10 | Whisper |
| `extract_and_ask(text)` | 11/10 | 요소 추출 + 질문 5~7개 한 번에 |
| `reextract(text, answers)` | 11/10 | 인터뷰 직후 재추출 |
| `split_scenes(...)` | 11/16 | 한국어 요약 + 영어 프롬프트 |

형식 오류는 최대 2회 재요청 후 예외 발생 → 서버가 `LLM_FAILED`로 변환
