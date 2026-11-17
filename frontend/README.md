# dream-restore 프론트엔드

Next.js와 React를 사용하는 화면입니다. B1 기록 흐름(`/record`)과 B2 결과 및 보관 화면(`/`)이 있습니다.

## 실행

Node.js 설치 후 이 폴더에서 다음 명령을 실행합니다.

```powershell
npm.cmd ci
npm.cmd run dev
```

브라우저에서 http://localhost:3000 을 엽니다.

## 현재 화면

- 꿈 기록하기(`/record`): 녹음 또는 글 입력, 내용 확인, 되묻기, 확신도 입력, 장면 생성 요청
- 스토리보드: 장면 선택, 내용과 확신도 수정, 이전 버전 조회
- 꿈 보관함: 제목 검색, 기록 상세, 스토리보드 재열람
- 영상 결과: 영상 미완료 안내와 결과 URL 기반 재생 화면

결과와 보관 화면은 현재 가상의 꿈을 사용하는 예시 모드입니다. 수정본은 현재 브라우저에만 저장됩니다. 실제 API 및 DB 저장, AI 이미지 재생성, 영상 생성은 후속 연결 대상입니다.

기록 화면은 `.env.local`에 `NEXT_PUBLIC_API_BASE_URL`을 넣으면 백엔드에 연결되고, 없으면 예시 모드로 동작합니다.

세부 파일 역할과 연동 범위는 features/dream-record/README.md, features/dream-results/README.md 를 참고하세요. API 공통 규칙은 ../docs/rules/ 에 있습니다.

## 확인 명령

```powershell
npm.cmd run lint
npm.cmd run build
```
