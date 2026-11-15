# 오류 응답 형식

코드 원본: `backend/app/core/errors.py`

```json
{ "error": { "code": "INVALID_STATE", "message": "화면에 보여 줄 수 있는 한국어 문장", "detail": {} } }
```

| HTTP | code | 상황 |
| --- | --- | --- |
| 400 | VALIDATION_ERROR | 요청 값 형식 오류, 저장된 데이터와 맞지 않는 값(예: 요소 목록에 없는 `element_id`) |
| 404 | NOT_FOUND | 대상 없음 |
| 409 | INVALID_STATE | 현재 상태에서 허용되지 않은 요청 |
| 409 | VERSION_CONFLICT | 장면 수정 기준 버전이 최신이 아님 |
| 413 | AUDIO_TOO_LARGE | 음성 파일 25MB 초과 |
| 415 | UNSUPPORTED_AUDIO | 허용하지 않은 음성 형식 |
| 502 | STT_FAILED, LLM_FAILED | 외부 AI 호출 실패 (질문 조회·요소 목록 조회에서 LLM 형식 오류가 재요청 후에도 남은 경우 포함) |
| 504 | UPSTREAM_TIMEOUT | 외부 AI 응답 시간 초과 (질문 조회·요소 목록 조회) |

400 VALIDATION_ERROR의 `detail`: 요청 형식 오류는 `{"errors": [...]}`, 목록에 없는 id는 `{"element_ids": [...]}`.

프론트엔드는 `code`로 분기하고 `message`는 그대로 표시할 수 있습니다.
