"""로컬 DB에 익명 샘플 꿈 5건을 상태별로 넣는다 (C2).

실행: backend 폴더에서  python scripts/seed.py
- 꿈 기록이 이미 있으면 아무것도 하지 않는다. 처음부터 다시 넣으려면 python scripts/reset_db.py
- DB에는 경로 문자열만 넣고 이미지·영상 파일은 만들지 않는다 (파일은 C·Worker 담당)

샘플 꿈 내용
- "학교 복도" 꿈은 D의 예시 JSON(docs/schemas/examples/)과 같은 내용
- 나머지 4건은 임시 문장. D의 익명화 테스트 데이터가 정리되면 SAMPLE_DREAMS를 교체한다
- 실제 참가자의 꿈 기록은 여기에 넣지 않는다
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import DreamStatus, JobStage, JobStatus, JobType
from app.db.session import SessionLocal
from app.models import Dream
from app.repositories import dreams, extractions, interview, jobs, renders, scenes
from app.storage import paths

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "examples"
BASE_TIME = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
STATUS_ORDER = list(DreamStatus)


def _example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


# 상태가 앞선 것부터. 각 꿈은 status 단계까지 데이터를 채운다
SAMPLE_DREAMS: list[dict] = [
    {
        "status": DreamStatus.RENDERED,
        "input_type": "text",
        "raw_text": (
            "어두운 학교 복도를 혼자 걷고 있었는데 형광등이 깜빡였다. "
            "분홍색 카디건을 입은 할머니가 노란 우산을 건네줬다. "
            "창밖을 보니 학교 밖이 온통 회색 바다였고 파도가 높아서 무서웠다."
        ),
        "raw_extraction": {"elements": _example("interview.json")["elements"]},
        "questions": _example("interview.json")["questions"],
        "answers": [
            "형광등이 깜빡이고 아무도 없었어요.",
            "흰 머리에 분홍색 카디건을 입고 계셨어요.",
            None,  # 기억 안 남
            "노란색 긴 장우산이었어요.",
            "파도가 아주 높았고 하늘도 회색이었어요.",
            "우산을 받고 마음이 놓이면서 깼어요.",
        ],
        "after_extraction": _example("elements.json"),
        "confidences": {
            "학교 복도": "high", "할머니": "high", "우산": "medium", "바다": "low", "두려움": "high", "안도감": "low",
        },
        "scenes": _example("scenes.json")["scenes"],
        "scene_confidence": ["high", "high", "low"],
    },
    {
        "status": DreamStatus.IMAGES_READY,
        "input_type": "voice",
        "raw_text": "시험장에 늦게 도착했는데 책상 위에 시험지 대신 하얀 고양이가 앉아 있었다. 감독관은 얼굴이 보이지 않았다.",
        "raw_extraction": {
            "elements": [
                {"type": "place", "name": "시험장", "description": "책상이 줄지어 있는 교실"},
                {"type": "object", "name": "하얀 고양이", "description": "책상 위에 앉아 있음"},
                {"type": "person", "name": "감독관", "description": "얼굴이 보이지 않음"},
                {"type": "emotion", "name": "초조함", "description": "늦어서 급했음"},
            ]
        },
        "questions": [
            {"order": 1, "target_element": "시험장", "question": "시험장 안에서 기억나는 것을 말해 주세요."},
            {"order": 2, "target_element": "하얀 고양이", "question": "고양이는 어떤 모습이었나요?"},
            {"order": 3, "target_element": "감독관", "question": "감독관에 대해 기억나는 것이 있나요?"},
            {"order": 4, "target_element": None, "question": "꿈이 어떻게 끝났는지 기억나나요?"},
            {"order": 5, "target_element": None, "question": "꿈에서 가장 강하게 남은 느낌은 무엇인가요?"},
        ],
        "answers": ["창문으로 햇빛이 들어왔어요.", "눈이 파랬어요.", None, "고양이가 창밖으로 뛰어나갔어요.", "초조함"],
        "after_extraction": {
            "elements": [
                {"type": "place", "name": "시험장", "description": "햇빛이 들어오는 교실"},
                {"type": "object", "name": "하얀 고양이", "description": "파란 눈, 책상 위에 앉아 있음"},
                {"type": "person", "name": "감독관", "description": "얼굴이 보이지 않음"},
                {"type": "emotion", "name": "초조함", "description": "늦어서 급했음"},
            ]
        },
        "confidences": {"시험장": "high", "하얀 고양이": "medium", "감독관": "low", "초조함": "high"},
        "scenes": [
            {"order": 1, "summary_ko": "늦게 시험장에 뛰어 들어간다.", "element_names": ["시험장", "초조함"], "image_prompt_en": "A sunlit classroom with rows of desks, someone rushing in late, dreamlike"},
            {"order": 2, "summary_ko": "책상 위에 파란 눈의 하얀 고양이가 앉아 있다.", "element_names": ["하얀 고양이", "시험장"], "image_prompt_en": "A white cat with blue eyes sitting on an exam desk, soft light, surreal"},
            {"order": 3, "summary_ko": "얼굴이 보이지 않는 감독관이 서 있다.", "element_names": ["감독관"], "image_prompt_en": "A faceless exam proctor standing at the front of a classroom, blurry, eerie"},
        ],
        "scene_confidence": ["high", "medium", "low"],
    },
    {
        "status": DreamStatus.SCENES_READY,
        "input_type": "text",
        "raw_text": "밤기차를 탔는데 창밖으로 별이 아주 가까이 지나갔다. 옆자리 친구가 뭔가 말했는데 소리가 들리지 않았다.",
        "raw_extraction": {
            "elements": [
                {"type": "place", "name": "밤기차", "description": "창이 큰 객실"},
                {"type": "object", "name": "별", "description": "창밖으로 가까이 지나감"},
                {"type": "person", "name": "친구", "description": "옆자리에 앉아 있음"},
            ]
        },
        "questions": [
            {"order": 1, "target_element": "밤기차", "question": "기차 안은 어떤 모습이었나요?"},
            {"order": 2, "target_element": "친구", "question": "친구는 어떤 모습이었나요?"},
            {"order": 3, "target_element": "별", "question": "별을 봤을 때 어떤 느낌이었나요?"},
            {"order": 4, "target_element": None, "question": "기차는 어디로 가고 있었나요?"},
            {"order": 5, "target_element": None, "question": "꿈이 어떻게 끝났는지 기억나나요?"},
        ],
        "answers": ["불이 꺼져 있고 조용했어요.", None, "신기하고 평온했어요.", None, "기차가 터널로 들어가면서 깼어요."],
        "after_extraction": {
            "elements": [
                {"type": "place", "name": "밤기차", "description": "불이 꺼진 조용한 객실"},
                {"type": "object", "name": "별", "description": "창밖으로 가까이 지나감"},
                {"type": "person", "name": "친구", "description": "옆자리에 앉아 있음"},
                {"type": "place", "name": "터널", "description": "기차가 들어간 어두운 터널"},
                {"type": "emotion", "name": "평온함", "description": "별을 보며 평온했음"},
            ]
        },
        "confidences": {"밤기차": "high", "별": "high", "친구": "low", "터널": "medium", "평온함": "medium"},
        "scenes": [
            {"order": 1, "summary_ko": "불 꺼진 밤기차 창밖으로 별이 지나간다.", "element_names": ["밤기차", "별", "평온함"], "image_prompt_en": "A dark night train cabin, stars passing very close outside the window, calm dreamy mood"},
            {"order": 2, "summary_ko": "옆자리 친구가 말하지만 소리가 들리지 않는다.", "element_names": ["친구", "밤기차"], "image_prompt_en": "A friend talking silently in the next seat of a dim train, muted, dreamlike"},
            {"order": 3, "summary_ko": "기차가 어두운 터널로 들어간다.", "element_names": ["터널"], "image_prompt_en": "A night train entering a dark tunnel, fading light, surreal"},
        ],
        "scene_confidence": ["high", "low", "medium"],
    },
    {
        "status": DreamStatus.INTERVIEWING,
        "input_type": "text",
        "raw_text": "어릴 때 살던 집 마당에 커다란 나무가 있었고, 그 아래에서 누군가 나를 부르고 있었다.",
        "raw_extraction": {
            "elements": [
                {"type": "place", "name": "옛날 집 마당", "description": "어릴 때 살던 집"},
                {"type": "object", "name": "큰 나무", "description": "마당 가운데에 있음"},
                {"type": "person", "name": "부르는 사람", "description": "나무 아래에 있음"},
            ]
        },
        "questions": [
            {"order": 1, "target_element": "옛날 집 마당", "question": "마당에서 기억나는 것을 말해 주세요."},
            {"order": 2, "target_element": "큰 나무", "question": "나무는 어떻게 생겼나요?"},
            {"order": 3, "target_element": "부르는 사람", "question": "부르는 사람에 대해 기억나는 것이 있나요?"},
            {"order": 4, "target_element": None, "question": "그때 계절이나 날씨가 기억나나요?"},
            {"order": 5, "target_element": None, "question": "꿈이 어떻게 끝났는지 기억나나요?"},
        ],
        "answers": ["낡은 평상이 있었어요.", None],  # 2개까지만 진행 (1개 답변, 1개 기억 안 남)
    },
    {
        "status": DreamStatus.RECORDED,
        "input_type": "voice",
        "raw_text": "엘리베이터를 탔는데 버튼이 전부 숫자가 아니라 색깔로 되어 있었다.",  # STT 결과, 아직 원문 확정 전
        "confirm": False,
    },
]


def _at(dream_index: int, minutes: float) -> datetime:
    return BASE_TIME + timedelta(days=dream_index, minutes=minutes)


def _finished_job(db: Session, dream_id: int, type_: JobType, start: datetime, seconds: float, target_id=None):
    job = jobs.create_job_or_get_active(db, dream_id, type_, target_id)
    job.status = JobStatus.SUCCEEDED.value
    job.started_at = start
    job.finished_at = start + timedelta(seconds=seconds)
    job.attempt = 1
    return job


def _seed_one(db: Session, index: int, data: dict) -> Dream:
    target = STATUS_ORDER.index(data["status"])
    dream = dreams.create_dream(db, input_type=data["input_type"], raw_text=data["raw_text"])
    dream.created_at = _at(index, 0)
    if data.get("confirm", True):
        dreams.update_confirmed_text(db, dream.id, data["raw_text"])
    if target == 0:
        return dream

    # interviewing: 원문 추출, 질문, 답변
    dreams.transition_status(db, dream.id, DreamStatus.RECORDED, DreamStatus.INTERVIEWING)
    extractions.save_extraction(db, dream.id, "raw", data["raw_extraction"], text_length=len(data["raw_text"]))
    questions = interview.save_questions(db, dream.id, data["questions"])
    for question, answer in zip(questions, data["answers"], strict=False):
        interview.save_answer(db, dream.id, question.id, answer=answer, skipped=answer is None)
    if target == 1:
        return dream

    # scenes_ready: 재추출, 확신도, 장면 v1
    answered_text = " ".join(a for a in data["answers"] if a)
    extractions.save_extraction(
        db, dream.id, "after_interview", data["after_extraction"], text_length=len(data["raw_text"]) + len(answered_text)
    )
    by_name = {e.name: e.id for e in extractions.list_elements(db, dream.id)}
    extractions.set_confidences(db, dream.id, {by_name[n]: c for n, c in data["confidences"].items()})
    scene_input = [s | {"confidence_level": c} for s, c in zip(data["scenes"], data["scene_confidence"], strict=True)]
    scene_list = scenes.create_scenes(db, dream.id, scene_input)
    _finished_job(db, dream.id, JobType.GENERATE_SCENES, _at(index, 10), 14)
    dreams.transition_status(db, dream.id, DreamStatus.INTERVIEWING, DreamStatus.SCENES_READY)

    # 이미지 생성: scenes_ready는 1장만 끝나고 나머지는 진행 중·대기, 이후 단계는 전부 끝남
    for i, scene in enumerate(scene_list):
        version = scene.current_version
        done = target > 2 or i == 0
        if done:
            version.final_prompt = f"{version.prompt_en}, soft watercolor dream style"
            version.model = "gpt-image-1"
            version.settings = {"size": "1536x1024", "quality": "medium"}
            version.image_path = str(paths.scene_original(dream.id, scene.id, version.version_no))
            version.generated_at = _at(index, 11 + i)
            version.status = JobStatus.SUCCEEDED.value
            _finished_job(db, dream.id, JobType.GENERATE_IMAGE, _at(index, 10.5), 20 + 8 * i, target_id=version.id)
        else:
            job = jobs.create_job_or_get_active(db, dream.id, JobType.GENERATE_IMAGE, version.id)
            if i == 1:
                version.status = JobStatus.RUNNING.value
                jobs.update_job(db, job.id, status=JobStatus.RUNNING, stage=JobStage.REQUESTING, attempt=1)
    if target == 2:
        return dream

    # images_ready
    dreams.transition_status(db, dream.id, DreamStatus.SCENES_READY, DreamStatus.IMAGES_READY)
    if target == 3:
        return dream

    # rendered: 영상
    render = renders.create_render(db, dream.id)
    renders.complete_render(
        db,
        render.id,
        video_path=str(paths.render_video(dream.id, render.id)),
        width=1280,
        height=720,
        duration=4.0 * len(scene_list),
        postprocess_settings={"blur": {"high": 0, "medium": 4, "low": 10}},
    )
    _finished_job(db, dream.id, JobType.RENDER_VIDEO, _at(index, 30), 25, target_id=render.id)
    dreams.transition_status(db, dream.id, DreamStatus.IMAGES_READY, DreamStatus.RENDERED)
    return dream


def seed(db: Session) -> list[Dream]:
    """SAMPLE_DREAMS를 넣고 만든 꿈 기록을 돌려준다. commit은 호출한 쪽에서 한다."""
    return [_seed_one(db, i, data) for i, data in enumerate(SAMPLE_DREAMS)]


def main() -> None:
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Dream)):
            print("꿈 기록이 이미 있어 샘플을 넣지 않았습니다. 다시 넣으려면: python scripts/reset_db.py")
            return
        made = seed(db)
        db.commit()
        for dream in made:
            print(f"dream {dream.id}: {dream.status}")
        print(f"샘플 꿈 {len(made)}건을 넣었습니다.")


if __name__ == "__main__":
    main()
