# app/llm — 인터뷰·장면 모듈 (정은수)

STT, 요소 추출, 되묻기 질문, 장면 분할, 이미지 프롬프트, 수정 해석.

- `prompts/`: 프롬프트 파일 (코드에 직접 쓰지 않음). 변경 내용은 `prompts/CHANGELOG.md`에 기록
- `schemas.py`: LLM 출력 Pydantic 스키마. 예시 JSON은 `docs/schemas/examples/`에 공유

서버에서 연결할 함수

| 함수 | 파일 | 상태 | 비고 |
| --- | --- | --- | --- |
| `transcribe(audio_path) -> str` | `interview.py` | 완료 | Whisper |
| `extract_and_ask(text) -> ExtractionResult` | `interview.py` | 완료 | 요소 추출 + 질문 5~7개 한 번에 |
| `reextract(text, answers) -> ReextractionResult` | `interview.py` | 완료 | 인터뷰 직후 재추출 |
| `split_scenes(text, answers, elements) -> SceneSplitResult` | `scenes.py` | 완료 | 장면 3~5개, 한국어 요약 + 영어 프롬프트 + 인물 외형 |

`split_scenes` 사용 예 (generate_scenes 작업 함수에서):

```python
result = split_scenes(text, answers, elements)   # elements: 인터뷰 후 요소 (ExtractedElement 목록)
create_scenes(db, dream_id, result.model_dump()["scenes"])
# result.characters: 인물별 영어 외형. generate_image payload의 characters에
#   {"name": c.name_en, "appearance": c.appearance_en} 로 넣으면 됩니다 (장면의 element_names에 있는 인물만)
```

- `image_prompt_en`에는 장면 내용만 들어갑니다. 화풍은 E2(`worker/image_gen/prompt.py`)가 붙이고, 확신도는 E1 블러로 표현합니다.

오류 (`client.py`, 전부 `LlmError` 상속)

| 예외 | 상황 |
| --- | --- |
| `LlmSchemaError` | 형식 오류. 최대 2회 재요청 후에도 실패 |
| `LlmCallError` | 호출 실패 (키 없음, 네트워크, 제공사 오류) |
| `LlmTimeoutError` (`LlmCallError` 상속) | 응답 시간 초과 (LLM, STT 공통) |
| `SttError` | 음성 인식 실패 |
| `SttEmptyResultError` (`SttError` 상속) | 인식된 말이 없음 |

실제 API로 돌려 보기: `cd backend && python scripts/try_interview.py` (`.env`에 `OPENAI_API_KEY` 필요)
