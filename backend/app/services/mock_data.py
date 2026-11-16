"""목업 샘플 데이터 (C-S1-01). 로직 없이 데이터만 둔다.

dream_id=1 꿈 하나가 생성 → 인터뷰 → 확신도 → 장면 → 영상까지 끝난 상태를 표현한다.
내용은 docs/schemas/examples/ 의 예시 꿈(학교 복도, 할머니, 우산, 바다)을 이어서 쓴다.
스키마 examples(/docs)와 목업 응답이 모두 이 상수를 쓴다.
"""
from app.storage import paths

DREAM_ID = 1
SCENES_JOB_ID = 1
RENDER_JOB_ID = 5
RENDER_ID = 1
AUDIO_ID = 1
CREATED_AT = "2026-11-14T09:00:00+09:00"
UPDATED_AT = "2026-11-14T09:03:00+09:00"

RAW_TEXT = (
    "어두운 학교 복도를 혼자 걷고 있었는데 형광등이 깜빡였다. "
    "분홍색 카디건을 입은 할머니가 노란 우산을 건네줬다. "
    "창밖을 보니 학교 밖이 온통 회색 바다였고 파도가 높아서 무서웠다."
)


def _image_url(scene_id: int) -> str:
    return paths.public_url(paths.scene_original(DREAM_ID, scene_id, 1))


VIDEO_URL = paths.public_url(paths.render_video(DREAM_ID, RENDER_ID))

# 요청 예시
DREAM_CREATE = {"input_type": "text", "text": RAW_TEXT}
DREAM_CONFIRM = {"confirmed_text": RAW_TEXT}
ANSWER_CREATE = {"question_id": 2, "answer": "흰 머리에 분홍색 카디건을 입고 있었어요.", "skipped": False}
CONFIDENCE_UPDATE = {
    "items": [
        {"element_id": 1, "confidence": "high"},
        {"element_id": 2, "confidence": "medium"},
        {"element_id": 3, "confidence": "high"},
        {"element_id": 4, "confidence": "low"},
        {"element_id": 5, "confidence": "medium"},
        {"element_id": 6, "confidence": "low"},
    ]
}
JOB_CREATE = {"type": "generate_scenes"}

# 응답 예시
DREAM_CREATED = {"dream_id": DREAM_ID, "status": "recorded"}
DREAM_CONFIRMED = {"dream_id": DREAM_ID, "status": "recorded"}

AUDIO_UPLOADED = {"audio_id": AUDIO_ID, "transcript": RAW_TEXT}

LATEST_RENDER_SUMMARY = {"render_id": RENDER_ID, "video_url": VIDEO_URL, "is_latest": True}

DREAM = {
    "dream_id": DREAM_ID,
    "status": "rendered",
    "input_type": "voice",
    "raw_text": RAW_TEXT,
    "confirmed_text": RAW_TEXT,
    "interview_progress": {"answered": 6, "total": 6},
    "active_job": None,
    "latest_render": LATEST_RENDER_SUMMARY,
    "created_at": CREATED_AT,
}

DREAM_LIST = {
    "items": [
        {
            "dream_id": DREAM_ID,
            "created_at": CREATED_AT,
            "thumbnail_url": _image_url(1),
            "summary": "어두운 학교 복도에서 할머니에게 노란 우산을 받고, 창밖의 회색 바다를 본 꿈",
            "status": "rendered",
        }
    ],
    "next_cursor": None,
}

INTERVIEW = {
    "questions": [
        {
            "question_id": 1,
            "order": 1,
            "target_element": "학교 복도",
            "question": "복도에서 기억나는 것을 자유롭게 말해 주세요.",
            "answered": True,
            "skipped": False,
        },
        {
            "question_id": 2,
            "order": 2,
            "target_element": "할머니",
            "question": "할머니는 어떤 모습이었나요?",
            "answered": True,
            "skipped": False,
        },
        {
            "question_id": 3,
            "order": 3,
            "target_element": "할머니",
            "question": "할머니가 무언가 말을 했나요? 기억나는 대로 말해 주세요.",
            "answered": True,
            "skipped": True,
        },
        {
            "question_id": 4,
            "order": 4,
            "target_element": "우산",
            "question": "우산은 어떻게 생겼나요?",
            "answered": True,
            "skipped": False,
        },
        {
            "question_id": 5,
            "order": 5,
            "target_element": "바다",
            "question": "바다를 봤을 때 주변은 어땠나요?",
            "answered": True,
            "skipped": False,
        },
        {
            "question_id": 6,
            "order": 6,
            "target_element": None,
            "question": "꿈이 어떻게 끝났는지 기억나나요?",
            "answered": True,
            "skipped": False,
        },
    ],
    "answered": 6,
    "total": 6,
}

ANSWER_SAVED = {"remaining": 0, "completed": True}

ELEMENTS = {
    "elements": [
        {
            "element_id": 1,
            "type": "place",
            "name": "학교 복도",
            "description": "어둡고 긴 복도, 형광등이 깜빡임",
            "confidence": "high",
        },
        {
            "element_id": 2,
            "type": "person",
            "name": "할머니",
            "description": "흰 머리에 분홍색 카디건을 입음",
            "confidence": "medium",
        },
        {
            "element_id": 3,
            "type": "object",
            "name": "우산",
            "description": "노란색 장우산",
            "confidence": "high",
        },
        {
            "element_id": 4,
            "type": "place",
            "name": "바다",
            "description": "창밖으로 보인 회색 바다, 파도가 높음",
            "confidence": "low",
        },
        {
            "element_id": 5,
            "type": "emotion",
            "name": "두려움",
            "description": "바다를 보고 무서웠음",
            "confidence": "medium",
        },
        {
            "element_id": 6,
            "type": "emotion",
            "name": "안도감",
            "description": "우산을 받고 마음이 놓임",
            "confidence": "low",
        },
    ]
}

JOB_QUEUED = {
    "job_id": SCENES_JOB_ID,
    "dream_id": DREAM_ID,
    "type": "generate_scenes",
    "target_id": None,
    "status": "queued",
    "stage": None,
    "attempt": 0,
    "error": None,
    "created_at": CREATED_AT,
    "started_at": None,
    "finished_at": None,
}

JOB = {
    **JOB_QUEUED,
    "status": "succeeded",
    "stage": "prompting",
    "attempt": 1,
    "started_at": CREATED_AT,
    "finished_at": UPDATED_AT,
}

JOB_FAILED_EXAMPLE = {
    **JOB,
    "status": "failed",
    "error": {"code": "LLM_SCHEMA", "message": "장면을 만들지 못했습니다. 다시 시도해 주세요."},
}

JOB_EVENTS = [
    {"job_id": SCENES_JOB_ID, "type": "generate_scenes", "status": "queued", "stage": None},
    {"job_id": SCENES_JOB_ID, "type": "generate_scenes", "status": "running", "stage": "splitting"},
    {"job_id": SCENES_JOB_ID, "type": "generate_scenes", "status": "running", "stage": "prompting"},
    {"job_id": SCENES_JOB_ID, "type": "generate_scenes", "status": "succeeded", "stage": "prompting"},
]

SCENES = {
    "scenes": [
        {
            "scene_id": 1,
            "order": 1,
            "summary_ko": "형광등이 깜빡이는 어두운 학교 복도를 혼자 걷는다.",
            "image_url": _image_url(1),
            "version_no": 1,
            "elements": [
                {"name": "학교 복도", "type": "place", "confidence": "high"},
                {"name": "두려움", "type": "emotion", "confidence": "medium"},
            ],
        },
        {
            "scene_id": 2,
            "order": 2,
            "summary_ko": "분홍색 카디건을 입은 할머니가 나타나 노란 우산을 건넨다.",
            "image_url": _image_url(2),
            "version_no": 1,
            "elements": [
                {"name": "학교 복도", "type": "place", "confidence": "high"},
                {"name": "할머니", "type": "person", "confidence": "medium"},
                {"name": "우산", "type": "object", "confidence": "high"},
                {"name": "안도감", "type": "emotion", "confidence": "low"},
            ],
        },
        {
            "scene_id": 3,
            "order": 3,
            "summary_ko": "창밖을 보니 학교 밖이 높은 파도가 치는 회색 바다다.",
            "image_url": _image_url(3),
            "version_no": 1,
            "elements": [
                {"name": "바다", "type": "place", "confidence": "low"},
                {"name": "우산", "type": "object", "confidence": "high"},
                {"name": "두려움", "type": "emotion", "confidence": "medium"},
            ],
        },
    ]
}

RENDER_CREATED = {"render_id": RENDER_ID, "job_id": RENDER_JOB_ID}

RENDER = {
    "render_id": RENDER_ID,
    "video_url": VIDEO_URL,
    "scene_versions": [
        {"scene_id": 1, "version_no": 1},
        {"scene_id": 2, "version_no": 1},
        {"scene_id": 3, "version_no": 1},
    ],
    "is_latest": True,
    "created_at": UPDATED_AT,
}
