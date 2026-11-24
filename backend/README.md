# backend

```
app/                FastAPI 서버
  main.py           앱 생성, CORS, 오류 처리, /storage 정적 파일
  api/              라우터 (프론트엔드가 호출하는 엔드포인트)
  core/             설정(config), 공통 상태값(enums), 오류 형식(errors)
  db/  models/      DB 연결, 테이블
  schemas/          API 요청/응답 스키마
  services/         비즈니스 로직, 상태 전이
  jobs/             작업 실행기, 작업 함수 규격(context), 등록(registry)
    submit.py       작업 등록 (진행 중인 같은 작업이 있으면 그 작업을 돌려줌)
    handlers/       장면 생성·이미지 작업 함수와 후처리
  storage/          파일 경로 규칙
  llm/              인터뷰·장면 모듈
worker/
  image_gen/        이미지 생성, 인물 일관성
  postprocess/      확신도 블러
  render/           FFmpeg 렌더링, TTS 나레이션
alembic/            DB 마이그레이션
scripts/            OpenAPI 내보내기
tests/              pytest
```

## API

- 인터뷰 조회(GET)는 질문이 없으면 이때 요소 추출과 질문 생성을 한다(LLM 호출, 약 5~8초). 꿈별 잠금으로 동시에 여러 번 불러도 LLM은 한 번만 호출된다(서버 프로세스 1개 기준. 여러 프로세스로 띄우면 LLM이 두 번 불릴 수 있지만 질문은 한 번만 저장된다).

## 이미지 생성 모드

장면 이미지는 저장소 루트 `.env`의 `IMAGE_GENERATION_MODE`에 따라 만든다.

| 값 | 동작 |
| --- | --- |
| `fake` (기본) | 이미지 API를 부르지 않아 비용이 없다. 장면마다 색이 다른 단색 PNG에 "FAKE IMAGE"와 꿈·장면 순서·버전을 적어 저장한다 |
| `real` | 실제 이미지 API를 부른다(`OPENAI_API_KEY` 필요, 비용 발생). 장면 하나당 최대 3번 호출한다(처음 1번 + 실패 시 재시도 2번) |

바꾸는 방법:

1. `.env`에서 `IMAGE_GENERATION_MODE=real`(또는 `fake`)로 고친다.
2. 서버를 다시 시작한다. 모드는 서버가 시작될 때 한 번만 읽으며, 시작 로그에 `이미지 생성 모드: real`처럼 찍힌다.

**실제 API로 확인을 마치면 반드시 `fake`로 되돌리고 서버를 다시 시작한다.** `real`로 둔 채 개발하면 장면을 만들 때마다 비용이 나간다. pytest는 `.env` 값과 관계없이 항상 `fake`로 돈다.

## 작업 후처리 등록

오래 걸리는 작업은 `submit_job`으로 만들고 실행기에 넘긴다. 같은 꿈·종류·`target_id`의 진행 중 작업이 있으면 새로 만들지 않는다.

```python
from app.jobs.submit import submit_job

job, created = submit_job(
    db, background_tasks,
    dream_id=dream_id, job_type=JobType.RENDER_VIDEO,
    target_id=render_id, payload={"render_id": render_id},
)
```

`created`가 False면 기존 작업을 돌려준 것이고 실행은 다시 예약하지 않는다. 장면 생성 API도 이 함수를 쓴다.

작업이 끝난 뒤의 DB 반영은 핸들러가 아니라 후처리에 둔다. 핸들러는 결과 dict만 돌려주고, 종류당 `on_success`와 `on_failure`를 하나씩 등록한다. 두 번 등록하면 서버가 뜰 때 오류가 난다. `render_video` 기준 의사 코드다.

```python
from app.jobs.registry import on_failure, on_success

@on_success(JobType.RENDER_VIDEO)
def save_render(db, job, result: dict) -> None:
    # job.status는 아직 running이다. succeeded 변경은 이 함수가 돌아온 뒤 같은 트랜잭션에서 한다.
    # 여기서 db.commit()하지 않는다.
    dream = dream_repo.get_dream(db, job.dream_id)
    ensure_transition(DreamStatus(dream.status), DreamStatus.RENDERED)
    dream_repo.transition_status(db, job.dream_id, dream.status, DreamStatus.RENDERED)


@on_failure(JobType.RENDER_VIDEO)
def mark_render_failed(db, job, error_code: str | None, error_message: str) -> None:
    # 작업 행은 이미 failed로 commit되어 있다. 여기서 db.commit()하지 않는다.
    # 재시도 중간에는 호출되지 않는다.
    ...
```

- 성공하면 실행기가 후처리 저장과 `succeeded`를 한 번에 commit한다.
- 실패하면 `failed`를 먼저 commit하고, 그 다음 `on_failure`가 남긴 변경을 commit한다. `on_failure`가 예외를 내면 traceback을 남기고, 새 세션에서 작업 종류별 최소 대비책(`runner.FAILURE_FALLBACKS`, 지금은 `generate_image`의 장면 버전 failed)을 실행한 뒤 실행기는 계속 돈다.
- 꿈 상태 전이는 `ensure_transition`으로 검사한 뒤 `transition_status`로 바꾼다.
- `on_success`가 실패하면 그 작업은 `failed`가 되고 핸들러는 다시 실행하지 않는다. 이미 만든 영상·이미지를 다시 만들지 않기 위해서다.
