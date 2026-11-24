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
| `prompt.py` | 프롬프트 조합: 공통 화풍 → 장면 내용 → 인물 외형 (→ 확신도 스타일: payload에 있을 때만) |
| `config.py` | 이미지 생성 설정 (공용 `app/core/config.py`와 같은 `.env`를 읽음) |

### payload (C가 Job API에서 넣어 줄 값)

```json
{
  "scene_id": 3,
  "version_no": 1,
  "image_prompt_en": "A long dark school hallway ...",
  "characters": [{"name": "grandma", "appearance": "white hair, pink cardigan, 70s"}],
  "style_prompt": null
}
```

`characters`, `style_prompt`는 선택입니다. D 출력에 등장 인물이 확정되면 C가 채워 줍니다.

### 세계관 인물 적용 (선택 기능)

등록된 인물(`world_entities`)이 꿈에 나오면 등록 외형을 그대로 넣어, 다른 날의 꿈에서도 같은 모습으로 그립니다.

```json
"characters": [
  {"name": "grandma", "age_range": "70s", "hair": "short white bob", "outfit": "pink knitted cardigan",
   "features": "round gold-rimmed glasses", "appearance": "holding a yellow umbrella"}
]
```

- 외형 문구는 `나이대 → 머리 → 옷차림 → 특징 → appearance` 순서로 만듭니다 (`Character.from_world_entity`).
  `appearance`는 이번 꿈에서만 다른 점이고 없어도 됩니다.
- `age_range`, `hair`, `outfit`, `features` 중 하나라도 있으면 세계관 인물로 처리하고, 없으면 기존처럼 `appearance`만 씁니다.
- **C 연결 방법**: 장면의 요소 중 `dream_elements.entity_id`가 있는 인물은 `world.get_entity()`로 읽어
  `name, age_range, hair, outfit, features`를 그대로 `characters`에 넣어 주세요.
- 이미지 프롬프트는 영어이므로 B2 등록 화면의 외형 입력도 영어 문구를 권장합니다. 한국어도 동작은 하지만 결과가 덜 정확할 수 있습니다.

**확신도 스타일 (선택)**: payload에 `confidence_style` 문장이 있으면 프롬프트 맨 뒤에 `Memory clarity: ...`로 붙입니다
(문구는 E1 `confidence_style_for`가 정하고 C가 payload에 넣음). 없거나 비어 있으면 붙이지 않아 선명한 원본 프롬프트가 됩니다.
블러 후처리(E1)와 겹치는지는 사용자 테스트에서 확인합니다.

### 반환값 (장면 버전에 기록)

`image_path`, `final_prompt`, `model`, `settings`(size, quality), `seed`(OpenAI는 지원 안 함 → `null`),
`attempts`, `elapsed_seconds`, `generated_at`

### 정해 둔 값 (팀 협의 전 임시)

- 크기 `1536x1024` 가로형: E1 렌더링(1280×720)이 남는 부분을 여백으로 채우므로 16:9에 가장 가까운 크기 사용
- 재시도: 시간 초과·일시적 오류(429, 5xx, 연결 오류, 손상된 이미지)는 작업 함수 안에서 최대 2회 재시도(1초, 2초 대기).
  콘텐츠 정책 거부·잘못된 요청은 바로 실패. **작업 실행기(C)에서는 추가 재시도하지 않아도 됩니다.**
- 설정은 `.env`의 `OPENAI_IMAGE_MODEL`, `IMAGE_SIZE`, `IMAGE_QUALITY`, `IMAGE_MAX_RETRIES`로 바꿀 수 있습니다.

테스트: `tests/test_image_gen.py`는 `backend/tests/` 담당자와 협의 후 추가 예정 (실제 API를 부르지 않음)
