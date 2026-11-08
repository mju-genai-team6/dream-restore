"""꿈 기록 상태 전이 규칙."""
from app.core.enums import DreamStatus
from app.core.errors import InvalidState

ALLOWED_TRANSITIONS: dict[DreamStatus, set[DreamStatus]] = {
    DreamStatus.RECORDED: {DreamStatus.INTERVIEWING},
    DreamStatus.INTERVIEWING: {DreamStatus.SCENES_READY},
    DreamStatus.SCENES_READY: {DreamStatus.IMAGES_READY},
    DreamStatus.IMAGES_READY: {DreamStatus.RENDERED},
    DreamStatus.RENDERED: set(),  # 장면 수정 후에도 rendered 유지, 영상만 최신 여부로 구분
}


def ensure_transition(current: DreamStatus, target: DreamStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidState(
            "현재 단계에서는 할 수 없는 요청입니다.",
            {"status": current.value, "target": target.value},
        )
