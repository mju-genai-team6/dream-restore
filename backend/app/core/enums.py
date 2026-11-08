"""팀 공통 상태값과 코드의 원본.

값 목록은 docs/rules/job-status.md 와 같아야 합니다. 바꾸면 docs/schemas/openapi.json 과
프론트엔드 타입도 함께 바뀝니다.
변경은 PR로만, 관련 담당자 리뷰 후 머지합니다.
"""
from enum import StrEnum


class DreamStatus(StrEnum):
    """꿈 기록 상태. 앞으로만 이동한다."""
    RECORDED = "recorded"
    INTERVIEWING = "interviewing"
    SCENES_READY = "scenes_ready"
    IMAGES_READY = "images_ready"
    RENDERED = "rendered"


class InputType(StrEnum):
    VOICE = "voice"
    TEXT = "text"


class ElementType(StrEnum):
    PERSON = "person"
    PLACE = "place"
    OBJECT = "object"
    EMOTION = "emotion"


class Confidence(StrEnum):
    """사용자 기억의 확신도 (확실 / 보통 / 흐릿). 값 이름은 S1 회의에서 확정."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExtractionPhase(StrEnum):
    RAW = "raw"                        # 원문만으로 추출
    AFTER_INTERVIEW = "after_interview"  # 인터뷰 답변 반영 후 재추출


class JobType(StrEnum):
    GENERATE_SCENES = "generate_scenes"        # D
    GENERATE_IMAGE = "generate_image"          # E2
    RENDER_VIDEO = "render_video"              # E1
    GENERATE_NARRATION = "generate_narration"  # E2 (선택)
    REVISE_SCENE = "revise_scene"              # D, E2 (선택)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStage(StrEnum):
    # generate_scenes
    SPLITTING = "splitting"
    PROMPTING = "prompting"
    # generate_image
    REQUESTING = "requesting"
    SAVING = "saving"
    # render_video (E1 제안)
    VALIDATING_INPUT = "validating_input"
    POSTPROCESSING = "postprocessing"
    COMPOSING = "composing"
    VERIFYING = "verifying"


class FailureCode(StrEnum):
    """작업 실패 사유."""
    TIMEOUT = "TIMEOUT"
    CONTENT_POLICY = "CONTENT_POLICY"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_INPUT = "INVALID_INPUT"
    LLM_SCHEMA = "LLM_SCHEMA"
    RENDER_FAILED = "RENDER_FAILED"
    INTERRUPTED = "INTERRUPTED"
