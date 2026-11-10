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

- 스토리보드: 장면 선택, 내용과 확신도 수정, 이전 버전 조회
- 꿈 보관함: 제목 검색, 기록 상세, 스토리보드 재열람
- 영상 결과: 영상 미완료 안내와 결과 URL 기반 재생 화면

현재는 가상의 꿈을 사용하는 예시 모드입니다. 수정본은 현재 브라우저에만 저장됩니다. 실제 API 및 DB 저장, AI 이미지 재생성, 영상 생성은 후속 연결 대상입니다.

세부 파일 역할과 연동 범위는 features/dream-results/README.md 를 참고하세요. API 공통 규칙은 ../docs/rules/ 에 있습니다.

## 확인 명령

```powershell
npm.cmd run lint
npm.cmd run build
```
