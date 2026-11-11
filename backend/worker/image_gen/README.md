# worker/image_gen — 이미지 생성, 인물 일관성 (김민진)

- 작업 함수 규격: `app/jobs/context.py`
- 저장 경로: `app/storage/paths.py`의 `scene_original` (규칙: `docs/rules/file-paths.md`)
- 원본 이미지는 덮어쓰지 않고 새 장면 버전으로 생성
- 장면 버전에 final_prompt, model, settings, seed, 생성 시간 기록
- 실패 사유: TIMEOUT, CONTENT_POLICY, PROVIDER_ERROR (`docs/rules/job-status.md`)

서버에 연결할 함수: `generate_image` 작업 함수 (11/17)

## 구현 현황

| 파일 | 내용 |
| --- | --- |
| `generate.py` | `handle_generate_image` (`@register(JobType.GENERATE_IMAGE)`), 장면 1개 = 작업 1개 |
| `prompt.py` | 프롬프트 조합: 공통 화풍 → 장면 내용 → 인물 외형 → 확신도 스타일 |

### payload (C가 Job API에서 넣어 줄 값)

```json
{
  "scene_id": 3,
  "version_no": 1,
  "image_prompt_en": "A long dark school hallway ...",
  "characters": [{"name": "grandma", "appearance": "white hair, pink cardigan, 70s"}],
  "style_prompt": null,
  "confidence_style": null
}
```

`characters`, `style_prompt`, `confidence_style`는 선택입니다. D 출력에 등장 인물·확신도가 확정되면 C가 채워 줍니다.

### 반환값 (장면 버전에 기록)

`image_path`, `final_prompt`, `model`, `settings`(size, quality), `seed`(OpenAI는 지원 안 함 → `null`),
`attempts`, `elapsed_seconds`, `generated_at`

### 정해 둔 값 (팀 협의 전 임시)

- 크기 `1536x1024` 가로형: E1 렌더링(1280×720)이 남는 부분을 여백으로 채우므로 16:9에 가장 가까운 크기 사용
- 재시도: 시간 초과·일시적 오류(429, 5xx, 연결 오류, 손상된 이미지)는 작업 함수 안에서 최대 2회 재시도(1초, 2초 대기).
  콘텐츠 정책 거부·잘못된 요청은 바로 실패. **작업 실행기(C)에서는 추가 재시도하지 않아도 됩니다.**
- 설정은 `.env`의 `OPENAI_IMAGE_MODEL`, `IMAGE_SIZE`, `IMAGE_QUALITY`, `IMAGE_MAX_RETRIES`로 바꿀 수 있습니다.

테스트: `pytest tests/test_image_gen.py` (실제 API를 부르지 않음)
