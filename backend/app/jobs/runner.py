"""작업 실행기 (S2 구현 예정).

- 작업 상태는 jobs 테이블에 저장
- 같은 꿈에 같은 종류의 작업이 진행 중이면 기존 jobId 반환
- 서버 재시작 시 running 작업은 INTERRUPTED로 실패 처리
- 이미지 생성 동시 요청 수는 settings.image_max_concurrency로 제한
"""
