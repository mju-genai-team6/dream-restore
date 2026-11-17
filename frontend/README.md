# dream-restore 프론트엔드

Next.js와 React를 사용하는 B2 결과 및 보관 화면입니다.

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

기본 실행은 가상의 꿈을 사용하는 예시 모드입니다. 장면 수정본은 현재 브라우저에 저장됩니다.

## 보관함을 테스트 API에 연결하기

팀 백엔드를 먼저 실행한 뒤, 이 폴더의 PowerShell에서 다음을 실행합니다.

```powershell
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"
npm.cmd run dev
```

`http://localhost:3000`에서 **서버 조회 모드**가 표시되면 보관함에서 꿈을 선택하고 **장면 열기**를 누릅니다. 꿈 목록은 `GET /dreams`, 장면은 `GET /dreams/{dream_id}/scenes`에서 받아옵니다.

목업 서버는 샘플 꿈을 반환하며, 이미지 파일이 없으면 화면에 **이미지 없음**이 표시됩니다. 서버 조회 모드에서는 보관함과 장면 조회를 제공합니다. 환경 변수를 설정하지 않은 경우 기존 예시 화면을 사용합니다.

기록 화면 안내는 [기록 흐름 README](features/dream-record/README.md), 결과 화면 안내는 [결과·보관 README](features/dream-results/README.md)를 참고하세요. API 공통 규칙은 ../docs/rules/ 에 있습니다.

## 확인 명령

```powershell
npm.cmd run lint
npm.cmd run build
```
