# dream-restore 프론트엔드

Next.js와 React를 사용하는 B1 꿈 기록 및 B2 결과·보관 화면입니다.

## 실행

Node.js 설치 후 이 폴더에서 다음 명령을 실행합니다.

```powershell
npm.cmd ci
npm.cmd run dev
```

브라우저에서 http://localhost:3000 을 엽니다.

## 현재 화면

- 꿈 기록 (`/record`): 음성·텍스트 입력, 원문 확인, 되묻기, 확신도 선택
- 스토리보드: 장면 선택, 내용과 확신도 수정, 이전 버전 조회
- 꿈 보관함: 제목 검색, 기록 상세, 스토리보드 재열람
- 영상 결과: 영상 미완료 안내와 결과 URL 기반 재생 화면
- 꿈 세계관 (`/world`): 인물과 장소 지도, 함께 나온 항목 연결, 세계관 항목 등록과 외형 수정

기본 실행은 가상의 꿈을 사용하는 예시 모드입니다. 장면 수정본은 현재 브라우저에 저장됩니다.

## 기록·결과·보관함을 팀 API에 연결하기

팀 백엔드를 먼저 실행한 뒤, 이 폴더(`frontend`)에 `.env.local` 파일을 만들고 다음 한 줄을 넣습니다. `.env.local`은 커밋되지 않습니다.

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

그다음 개발 서버를 실행합니다. 이미 켜져 있었는데 주소가 반영되지 않으면 껐다가 다시 켭니다.

```
npm run dev                # Windows PowerShell에서 막히면 npm.cmd run dev
```

잠깐만 서버에 붙여 보고 싶다면 파일 대신 환경 변수로 지정해도 됩니다. Windows PowerShell은 `$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"`을 먼저 실행하고, macOS/Linux는 `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev`로 실행합니다. 이 방법은 그 터미널을 닫으면 사라집니다.

`http://localhost:3000`에서 **서버 조회 모드**가 표시되면 보관함에서 꿈을 선택하고 **장면 열기**를 누릅니다. **꿈 기록하기**에서 기록을 마쳐도 해당 꿈의 결과 화면으로 이동합니다. 새 DB 변경을 받았다면 백엔드 환경에서 `alembic upgrade head`를 먼저 실행합니다.

- 보관함·장면은 실제 DB 조회 API를 사용합니다. `/?dreamId=숫자&jobId=숫자`로 기록한 꿈과 생성 진행 상태를 바로 엽니다. 영상 화면 주소는 `/?dreamId=숫자&view=video`입니다.
- 장면·이미지·영상 생성 중에는 약 4초마다 상태를 다시 확인합니다. 완료·실패·통신 오류·화면 이탈 때 멈추며, 최대 3분 뒤에는 새로고침을 안내합니다.
- 이미지 생성 중·실패·파일 조회 실패를 구분합니다. 실패한 이미지는 **실패한 이미지 다시 만들기**, 장면 생성 실패는 **장면 생성 다시 시도**로 재요청할 수 있습니다.
- 이미지가 모두 완성되면 **영상 만들기**를 누릅니다. 완료되면 영상 화면에서 재생하며, 최신 장면과 다른 이전 영상은 별도로 표시합니다.
- 백엔드의 `IMAGE_GENERATION_MODE=fake`는 외부 이미지 API를 사용하지 않는 시험용 이미지입니다. 실제 이미지 생성은 팀의 리허설·시연 계획에 맞춰 진행합니다. 이미지 모드와 별개로 음성 인식·인터뷰·장면 분할의 실제 LLM 호출은 비용이 들 수 있습니다.
- 환경 변수를 지정하지 않으면 기존 예시 모드입니다. B1의 예시 기록과 B2의 예시 보관함 데이터는 별개이므로 전체 연결은 서버 조회 모드에서 확인합니다.

기록 화면 안내는 [기록 흐름 README](features/dream-record/README.md), 결과 화면 안내는 [결과·보관 README](features/dream-results/README.md), 세계관 화면 안내는 [세계관 README](features/dream-world/README.md)를 참고하세요. API 공통 규칙은 ../docs/rules/ 에 있습니다.

## 확인 명령

```powershell
npm.cmd run lint
npm.cmd test
npm.cmd run build
```
