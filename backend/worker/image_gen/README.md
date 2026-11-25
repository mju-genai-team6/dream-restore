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

`image_path`, `final_prompt`, `model`, `settings`(size, quality, 순화했으면 `policy_softened: true`),
`seed`(OpenAI는 지원 안 함 → `null`), `attempts`, `elapsed_seconds`, `generated_at`

### 정책 거부 시 표현 완화 규칙 (E2 결정, D에 통보)

악몽처럼 무섭거나 폭력적인 장면은 콘텐츠 정책으로 거부될 수 있습니다 (계획서 3.2).

1. 거부되면 프롬프트 앞에 순화 문구(`prompt.py`의 `SOFTEN_PREFIX`)를 붙여 **한 번만** 다시 시도합니다.
   장면 내용은 그대로 두고 "부드럽고 상징적으로, 피·부상·무기 사용·노골적 폭력은 그리지 않음"으로 표현 방식만 완화합니다.
2. 또 거부되면 그 장면만 `CONTENT_POLICY`로 실패합니다. 다른 장면은 계속 진행됩니다.
3. 순화해서 만든 이미지는 `final_prompt`에 순화 문구가 남고 `settings.policy_softened = true`로 기록됩니다.
4. 끄려면 `.env`에 `IMAGE_SOFTEN_ON_POLICY=false` (거부되면 바로 실패).

D의 장면 프롬프트는 바꾸지 않습니다. D가 처음부터 표현을 완화해 주면 거부 자체가 줄어듭니다.

### 계획서와 다르게 진행한 것

- **이미지 API 후보 2~3개 비교 (계획서 3.1)**: 하지 않았습니다. 팀에 OpenAI 키만 있어 다른 회사 API는 키와 예산이
  별도로 필요해 개발 범위 밖으로 두었습니다. `gpt-image-2` 하나로 진행했고, 생성 시간은 실측 20장으로 기록했습니다 (#40).
- **시드 고정 (계획서 2장, 3.3 조건 C)**: OpenAI 이미지 API가 seed를 지원하지 않습니다. 인물 일관성 실험의 C 조건은
  화풍·구도 고정만 적용했고, 장면 버전의 `seed`는 `null`로 기록합니다. 재현은 기록한 `final_prompt`와 설정으로 다시 생성하는 수준입니다.
- **정책 거부 완화 (계획서 3.2)**: D와 합의 대신 E2가 위 규칙으로 정하고 D에 통보했습니다.

### 정해 둔 값 (팀 협의 전 임시)

- 크기 `1536x1024` 가로형: E1 렌더링(1280×720)이 남는 부분을 여백으로 채우므로 16:9에 가장 가까운 크기 사용
- 재시도: 시간 초과·일시적 오류(429, 5xx, 연결 오류, 손상된 이미지)는 작업 함수 안에서 최대 2회 재시도(1초, 2초 대기).
  콘텐츠 정책 거부는 위 순화 규칙으로 한 번만 더 시도하고, 잘못된 요청은 바로 실패. **작업 실행기(C)에서는 추가 재시도하지 않아도 됩니다.**
- 설정은 `.env`의 `OPENAI_IMAGE_MODEL`, `IMAGE_SIZE`, `IMAGE_QUALITY`, `IMAGE_MAX_RETRIES`, `IMAGE_SOFTEN_ON_POLICY`로 바꿀 수 있습니다.

테스트: `tests/test_image_confidence_style.py`, `tests/test_image_policy_soften.py` (실제 API를 부르지 않음)
