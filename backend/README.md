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
