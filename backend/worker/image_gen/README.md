# worker/image_gen — 이미지 생성, 인물 일관성 (김민진)

- 작업 함수 규격: `app/jobs/context.py`
- 저장 경로: `app/storage/paths.py`의 `scene_original` (규칙: `docs/rules/file-paths.md`)
- 원본 이미지는 덮어쓰지 않고 새 장면 버전으로 생성
- 장면 버전에 final_prompt, model, settings, seed, 생성 시간 기록
- 실패 사유: TIMEOUT, CONTENT_POLICY, PROVIDER_ERROR (`docs/rules/job-status.md`)

서버에 연결할 함수: `generate_image` 작업 함수 (11/17)
