# B1 기록 흐름 화면

꿈 입력부터 되묻기, 확신도 입력, 장면 생성 요청까지의 화면입니다. 요청한 뒤의 화면은 B2(`features/dream-results/`)가 맡습니다.

## 화면

| 단계 | 주소 | 파일 | 사용 API |
| --- | --- | --- | --- |
| 꿈 입력 | `/record` | `RecordStep.tsx` | `POST /dreams`, `POST /dreams/{id}/audio` |
| 내용 확인 | `/record/[dreamId]/transcript` | `TranscriptStep.tsx` | `GET /dreams/{id}`, `PATCH /dreams/{id}` |
| 되묻기 | `/record/[dreamId]/interview` | `InterviewStep.tsx` | `GET`, `POST /dreams/{id}/interview` |
| 확신도 | `/record/[dreamId]/confidence` | `ConfidenceStep.tsx` | `GET /dreams/{id}/elements`, `PUT /dreams/{id}/elements/confidence`, `POST /dreams/{id}/jobs` |
| 이어하기 | `/record/[dreamId]` | `ResumeStep.tsx` | `GET /dreams/{id}` |

- 꿈 입력: 녹음은 5분에서 자동으로 멈춥니다. Chrome은 webm, iOS Safari는 mp4로 올라갑니다. 마이크를 쓸 수 없으면 글로 쓰기로 바꿔 줍니다.
- 글로 쓴 꿈은 서버가 원문을 바로 확정하므로 내용 확인 단계 없이 되묻기로 갑니다.
- 내용 확인에서 '다시 녹음'을 누르면 `/record?dreamId={id}`로 돌아가 같은 꿈 기록에 새 녹음을 올립니다.
- 되묻기: 질문을 하나씩 보여 주고, '잘 기억 안 남'은 `skipped: true`로 보냅니다.
- 확신도: 고를 때마다 그 요소만 저장하고, '장면 만들기'를 누르면 전체를 한 번 더 저장한 뒤 장면 생성을 요청합니다. 버튼을 여러 번 눌러도 요청은 한 번만 나갑니다.
- 모든 단계 화면은 열릴 때 `GET /dreams/{id}`로 꿈 기록 상태를 보고, 지금 단계가 아니면 맞는 화면으로 보냅니다(`api.ts`의 `currentStep`). 새로고침, 뒤로 가기, 주소 직접 입력이 모두 이 규칙을 따릅니다.

| 꿈 기록 상태 | 보내는 화면 |
| --- | --- |
| `recorded`, 변환된 글 없음 | 꿈 입력 |
| `recorded`, 확정 전 | 내용 확인 |
| `recorded`, 확정됨 | 되묻기 |
| `interviewing`, 남은 질문 있음 | 되묻기 |
| `interviewing`, 모두 답함 | 확신도 |
| 장면 생성 작업 진행 중, `scenes_ready` 이후 | B2 결과 화면 |

## 실행

`frontend/.env.local`에 백엔드 주소를 넣고 `npm.cmd run dev`를 실행한 뒤 `http://localhost:3000/record`를 엽니다.

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

주소를 넣지 않으면 예시 모드로 동작합니다. 예시 모드는 `mock-server.ts`가 서버 대신 응답하고, 주소 끝에 `?fail=stt`, `?fail=llm`, `?fail=save`를 붙이면 실패 화면을 볼 수 있습니다.

마이크는 HTTPS와 localhost에서만 켜집니다. 그 밖의 주소에서는 글로 쓰기만 됩니다.

## 파일 구성

| 파일 | 내용 |
| --- | --- |
| `api.ts` | 서버 요청 함수, 응답 형식 변환, 오류 처리, 꿈 기록 상태로 단계 정하기 |
| `useRequest.ts` | 불러오기, 로딩, 실패, 다시 시도와 단계 이동 |
| `types.ts` | 화면 데이터 형식 |
| `StepLayout.tsx` | 메뉴, 제목, 단계 안내가 있는 공통 틀과 로딩, 실패 표시 |
| `Icon.tsx` | 선 아이콘 |
| `mock-server.ts`, `mock-data.ts` | 예시 모드용 가짜 서버와 데이터 |
| `dream-record.module.css` | 배치와 반응형 스타일 |

화면 틀, 색, 화면 너비 기준은 B2 결과 화면과 같은 값을 씁니다. 확신도 문구(확실, 보통, 흐릿)와 색도 B2 스토리보드와 같습니다.

## 서버와 맞춘 내용

- 오류는 서버가 준 `message`를 그대로 보여 줍니다(`docs/rules/error-format.md`). 서버에 닿지 못했거나 2분 넘게 응답이 없을 때만 화면에서 문구를 만듭니다.
- 음성 업로드, 첫 질문 조회, 첫 요소 조회는 요청 안에서 AI 응답을 기다리므로 로딩 문구에 걸리는 시간을 적었습니다.
- 질문 조회 응답에는 답변 내용이 없습니다. 그래서 내가 쓴 답은 브라우저 탭(sessionStorage)에만 두고, 탭을 닫았다 다시 열면 '답변함'으로만 보입니다.
- 장면 생성 요청 뒤에는 `api.ts`의 `resultsPath()` 주소로 이동합니다. 지금은 `/?dreamId={id}&jobId={jobId}`이고, `jobId`는 `POST /dreams/{id}/jobs`가 돌려준 값입니다.

## 남은 일

- B2 결과 화면이 주소의 `dreamId`, `jobId`로 해당 꿈의 진행 상태와 장면을 보여 주도록 연결되면, 정해진 주소에 맞춰 `resultsPath()`를 바꿉니다.
- `Confidence`, `DreamStatus` 타입과 `Icon.tsx`는 B2와 겹치므로 공통 위치로 옮길 예정입니다.
- 실제 iOS Safari 기기에서의 녹음과 실제 STT, LLM 키를 넣은 서버에서의 확인이 남았습니다.
