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

### target_id

작업 종류마다 `jobs.target_id`가 가리키는 대상이 다릅니다. 외래키는 없고 id만 저장합니다 (`docs/rules/data-model.md`).

| 작업 종류 | target_id |
| --- | --- |
| `generate_scenes` | NULL |
| `generate_image` | `scene_version_id` (`scene_versions.id`) |
| `render_video` | `render_id` (`renders.id`) |
| `generate_narration` (선택) | `scenes.id` |
| `revise_scene` (선택) | `scenes.id` |

- 실행 상태: `queued`, `running`, `succeeded`, `failed`
- 실패 사유: `TIMEOUT`, `CONTENT_POLICY`, `PROVIDER_ERROR`, `INVALID_INPUT`, `LLM_SCHEMA`, `RENDER_FAILED`, `INTERRUPTED`
- `JobError`가 아닌 예외로 실패한 작업은 DB에 `error_code`를 NULL로 두고, API에서는 `error.code = "INTERNAL_ERROR"`로 보여 준다 (`FailureCode` 값이 아님)
- 확신도: `high`(확실), `medium`(보통), `low`(흐릿) — 값 이름은 11/7 회의에서 확정
