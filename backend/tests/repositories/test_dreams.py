from datetime import UTC, datetime, timedelta

from app.core.enums import DreamStatus
from app.models import Dream
from app.repositories import audio, dreams, extractions, scenes
from tests.repositories.helpers import (
    ELEMENTS_PAYLOAD,
    SCENES,
    committed_dream,
    run_concurrently,
)


def test_create_and_get_dream(db):
    dream = dreams.create_dream(db, input_type="voice", raw_text=None)
    assert dream.id is not None
    assert dream.status == DreamStatus.RECORDED
    assert dream.created_at is not None
    assert dreams.get_dream(db, dream.id) is dream
    assert dreams.get_dream(db, 999_999_999) is None


def test_update_confirmed_text(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    updated = dreams.update_confirmed_text(db, dream.id, "확정 원문")
    assert updated.confirmed_text == "확정 원문"
    assert dreams.update_confirmed_text(db, 999_999_999, "x") is None


def test_transition_status_only_from_expected_state(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    assert dreams.transition_status(db, dream.id, DreamStatus.RECORDED, DreamStatus.INTERVIEWING) is True
    assert dream.status == DreamStatus.INTERVIEWING  # 세션의 객체에도 반영
    # 이미 interviewing이므로 recorded에서 출발하는 변경은 실패
    assert dreams.transition_status(db, dream.id, DreamStatus.RECORDED, DreamStatus.INTERVIEWING) is False
    assert dreams.transition_status(db, 999_999_999, DreamStatus.RECORDED, DreamStatus.INTERVIEWING) is False


def test_concurrent_transition_succeeds_once(db_engine):
    """완료 기준: 두 요청이 동시에 같은 상태 변경을 시도해도 한 번만 성공한다."""
    with committed_dream(db_engine) as dream_id:
        results = run_concurrently(
            db_engine,
            lambda s: dreams.transition_status(s, dream_id, DreamStatus.RECORDED, DreamStatus.INTERVIEWING),
            n=5,
        )
        assert sorted(results) == [False, False, False, False, True]


def test_add_audio_file(db):
    dream = dreams.create_dream(db, input_type="voice", raw_text=None)
    row = audio.add_audio_file(
        db, dream_id=dream.id, path=f"dreams/{dream.id}/audio/1.webm", mime_type="audio/webm", size=1024, duration=3.5
    )
    assert row.id is not None and row.dream_id == dream.id and row.size == 1024


def test_list_dreams_pages_newest_first_with_thumbnail(db):
    base = datetime(2026, 11, 1, tzinfo=UTC)
    made = []
    for i in range(5):
        dream = Dream(input_type="text", raw_text=f"꿈 {i}", created_at=base + timedelta(days=i))
        db.add(dream)
        db.flush()
        made.append(dream)
    # 가장 최근 꿈에만 장면과 이미지가 있다
    newest = made[-1]
    extractions.save_extraction(db, newest.id, "raw", ELEMENTS_PAYLOAD, text_length=10)
    first_scene = scenes.create_scenes(db, newest.id, SCENES)[0]
    first_scene.current_version.image_path = "dreams/x/scenes/1/v1/original.png"
    db.flush()

    # 다른 테스트 데이터가 섞이지 않도록 이 테스트에서 만든 꿈만 본다
    ids = {d.id for d in made}
    page1 = dreams.list_dreams(db, limit=2)
    assert [item.dream.id for item in page1.items] == [made[4].id, made[3].id]
    assert page1.items[0].thumbnail_path == "dreams/x/scenes/1/v1/original.png"
    assert page1.items[0].summary == "복도를 걷는다."
    assert page1.items[1].thumbnail_path is None and page1.items[1].summary is None

    page2 = dreams.list_dreams(db, cursor=page1.next_cursor, limit=2)
    page3 = dreams.list_dreams(db, cursor=page2.next_cursor, limit=2)
    seen = [i.dream.id for p in (page1, page2, page3) for i in p.items if i.dream.id in ids]
    assert seen == [d.id for d in reversed(made)]
