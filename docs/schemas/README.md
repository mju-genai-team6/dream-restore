# schemas

- `openapi.json`: 백엔드에서 자동 생성합니다. 직접 수정하지 않습니다.
  - 생성: `cd backend && python scripts/export_openapi.py`
  - 프론트엔드 타입 생성: `npx openapi-typescript ../docs/schemas/openapi.json -o src/types/api.ts`
- `examples/`: 실제 API가 완성되기 전 목업 개발용 예시 응답
  - 예정: `elements.json`, `interview.json`, `scenes.json`, `job.json` (11/5까지)
