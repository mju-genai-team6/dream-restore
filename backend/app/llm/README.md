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

- **즉시 응답 오류는 `LLM_FAILED`, 작업 실패 사유는 `LLM_SCHEMA`입니다.** 질문 생성·재추출처럼 요청 안에서 부르면 서버가 `LLM_FAILED`(502)로 응답하고, `generate_scenes` 작업 안에서 형식 오류가 나면 작업 실패 사유가 `LLM_SCHEMA`가 됩니다.
- 응답이 없을 때: OpenAI SDK 자체 재시도는 1회(`OPENAI_MAX_RETRIES`)라 오류까지 최대 `LLM_TIMEOUT_SECONDS` × 2가 걸립니다 (기본 30초라 약 60초).
- 스키마 외 검사(재요청 대상): 요소 name 중복, 질문 대상이 요소 목록에 없음, 장면 `element_names`가 비어 있음, 장면에 인물·장소·물건이 없음, 인물별 `characters` 누락.
- STT 무음·환각: 말소리가 없는 녹음에서 Whisper가 지어낸 문장("고맙습니다.", "시청해주셔서 감사합니다.", "MBC 뉴스 ...입니다")은 구간별 `no_speech_prob`(0.6 이상)와 알려진 문장 목록으로 버립니다. 남는 말이 없으면 `SttEmptyResultError`입니다. 버린 구간은 경고 로그에 남습니다.
- 재요청 없이 코드에서 걸러 내는 것: 장면 `element_names` 중 요소 목록에 없는 이름, `characters` 중 person이 아닌 항목(동물·물건)과 중복. 그래서 돌려받은 결과의 `element_names`와 `characters`에는 요소 목록에 있는 이름만 들어 있습니다. 뺀 이름은 경고 로그(`app.llm.scenes`)에 남습니다.

실제 API로 돌려 보기: `cd backend && python scripts/try_interview.py` (`.env`에 `OPENAI_API_KEY` 필요)
