"""작업 상태 변경 알림. SSE는 두지 않는다(화면은 GET /jobs/{id}, GET /dreams/{id}/scenes를 주기적으로 조회)."""
from app.schemas.jobs import JobSummary


def publish_job_event(summary: JobSummary) -> None:
    """실행기가 작업 상태·단계를 commit한 뒤 부른다. 지금은 받는 곳이 없고, 테스트가 바꿔 끼워 순서를 확인한다."""
