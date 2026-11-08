# 상태값 규칙

코드 원본: `backend/app/core/enums.py` (이 문서와 항상 같아야 함)

## 꿈 기록 상태 (앞으로만 이동)

`recorded` → `interviewing` → `scenes_ready` → `images_ready` → `rendered`

실패는 꿈 기록 상태가 아니라 작업 상태로 표시합니다.

## 작업(Job)

| 작업 종류 | 처리 | 담당 폴더 |
| --- | --- | --- |
| `generate_scenes` | 장면 분할, 프롬프트 생성 | `app/llm/` |
| `generate_image` | 장면 이미지 생성 | `worker/image_gen/` |
| `render_video` | 확신도 블러, FFmpeg 합성 | `worker/postprocess/`, `worker/render/` |
| `generate_narration` (선택) | TTS | `worker/render/` |
| `revise_scene` (선택) | 장면 수정 | `app/llm/`, `worker/image_gen/` |

- 실행 상태: `queued`, `running`, `succeeded`, `failed`
- 실패 사유: `TIMEOUT`, `CONTENT_POLICY`, `PROVIDER_ERROR`, `INVALID_INPUT`, `LLM_SCHEMA`, `RENDER_FAILED`, `INTERRUPTED`
- 확신도: `high`(확실), `medium`(보통), `low`(흐릿) — 값 이름은 11/7 회의에서 확정
