# dream-restore

**대화형 꿈 복원 및 애니메이션 서비스** — 생성형 인공지능 수업 6팀

## 프로젝트 소개

잠에서 깬 직후 꿈은 빠르게 잊힙니다. dream-restore는 사용자가 꿈을 **음성으로 말하면** AI가 **되묻기 질문**으로 흐릿한 기억을 보충하고,
각 기억의 **확신도**를 반영한 장면별 이미지와 짧은 **슬라이드 영상**으로 꿈을 보존하는 서비스입니다.

- 확실하게 기억나는 장면은 선명하게, 흐릿한 장면은 흐릿하게 표현합니다.
- 장면이 바뀌어도 같은 인물은 같은 모습으로 보이도록 인물 일관성을 유지합니다.
- 완성된 꿈은 보관함에 저장해 다시 볼 수 있습니다.

## 처리 흐름 (MVP)

```
음성 입력
  → STT (Whisper)
  → LLM 요소 추출 · 되묻기 질문 5~7개
  → 확신도 입력 (확실 / 보통 / 흐릿)
  → 장면 3~5개 분할
  → 장면별 이미지 생성
  → 확신도 기반 블러 후처리 (Pillow)
  → 슬라이드 영상 렌더링 (FFmpeg, TTS 나레이션)
  → 저장
```

이미지 생성과 렌더링처럼 오래 걸리는 작업은 Job 단위로 처리합니다. 처음에는 FastAPI `BackgroundTasks`로 시작하고, 이후 Redis 기반 작업 큐로 옮깁니다.

## 기술 스택

| 구분 | 사용 기술 |
| --- | --- |
| 프론트엔드 | Next.js |
| 백엔드 | FastAPI |
| 작업 큐 | FastAPI BackgroundTasks → Redis |
| 데이터베이스 | PostgreSQL |
| 음성 인식 (STT) | Whisper |
| 언어 모델 | LLM API |
| 이미지 생성 | 이미지 생성 API |
| 이미지 후처리 | Pillow |
| 영상 렌더링 | FFmpeg |
| 음성 합성 | TTS |

## 폴더 구조와 담당

```
dream-restore/
├── frontend/                       # Next.js 화면
├── backend/
│   ├── app/                        # FastAPI 서버
│   └── worker/
│       ├── image_gen/              # 이미지 생성, 인물 일관성
│       ├── postprocess/            # 확신도 블러
│       └── render/                 # FFmpeg 렌더링, TTS 나레이션
├── experiments/
│   ├── confidence_blur/            # 확신도 표현 실험
│   └── character_consistency/      # 인물 일관성 실험
└── docs/                           # 스키마·규칙 문서
    └── meetings/                   # 회의록
```

| 폴더 | 내용 | 담당 |
| --- | --- | --- |
| `frontend/` | 기록 흐름 (음성 입력, 되묻기 질문, 확신도 입력) | 이연주 |
| `frontend/` | 결과·보관 흐름 (장면·영상 결과, 보관함) | 인진은 |
| `backend/app/` | 인터뷰·장면 모듈 | 정은수 |
| `backend/app/` | 세계관·Job API | 박예나 |
| `backend/worker/image_gen/` | 이미지 생성, 인물 일관성 | 김민진 |
| `backend/worker/postprocess/` | 확신도 블러 | 이종민 |
| `backend/worker/render/` | FFmpeg 렌더링 | 이종민 |
| `backend/worker/render/` | TTS 나레이션 | 김민진 |
| `experiments/confidence_blur/` | 확신도 실험 | 이종민 |
| `experiments/character_consistency/` | 인물 일관성 실험 | 김민진 |
| `docs/` | LLM 출력 JSON 스키마, 작업 상태값, 파일 경로 규칙, 회의록 | 공동 |

## 시작 방법

> 아직 코드가 없는 초기 단계입니다. 각 모듈이 만들어지면 이 절을 실제 명령어로 갱신해 주세요.

### 1. 저장소 받기

```bash
git clone https://github.com/mju-genai-team6/dream-restore.git
cd dream-restore
```

### 2. 환경 변수 설정

`.env.example`(추가 예정)을 복사해 `.env`를 만들고 각자 발급받은 키를 채웁니다. `.env`는 절대 커밋하지 않습니다.

```bash
cp .env.example .env
```

### 3. 사전 설치

- Node.js (LTS), Python 3.11 이상
- PostgreSQL
- FFmpeg (`ffmpeg -version`으로 설치 확인)

### 4. 실행 (예정)

```bash
# 백엔드
cd backend
python -m venv .venv
pip install -r requirements.txt
uvicorn app.main:app --reload
```

```bash
# 프론트엔드
cd frontend
npm install
npm run dev
```

## 협업 규칙

### 브랜치와 Pull Request

- `main`에 직접 push하지 않습니다.
- `feature/<역할>-<작업>` 브랜치에서 작업한 뒤 Pull Request를 올립니다.
  - 예: `feature/frontend-record-page`, `feature/imagegen-character-consistency`, `feature/render-ffmpeg-slide`
- 리뷰를 받은 뒤 `main`에 병합합니다.

### API 키

- API 키는 `.env`에만 두고 커밋하지 않습니다.
- 새로운 키가 필요하면 `.env.example`에 **키 이름만** 추가합니다. (값은 비워 둡니다)

### 생성 결과물

- 생성된 이미지·영상·음성 파일은 커밋하지 않습니다.
- 결과물은 `storage/`, `outputs/` 폴더에 저장하며, 이 폴더들은 `.gitignore`에 등록합니다.
- 상세한 파일 경로 규칙은 `docs/`에 정리합니다.
