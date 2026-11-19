"""인물 외형 저장·조회 (C 요청): 장면 생성 때 저장하고 이미지 재시도·장면 수정 때 다시 읽는다."""

import pytest

from app.repositories import InvalidData, dreams, extractions, scenes
from tests.repositories.helpers import ELEMENTS_PAYLOAD, SCENES

GRANDMA = {"name": "할머니", "name_en": "the grandmother", "appearance_en": "short white hair, pink cardigan"}


@pytest.fixture
def dream_with_scenes(db):
    dream = dreams.create_dream(db, input_type="text", raw_text="원문")
    extractions.save_extraction(db, dream.id, "after_interview", ELEMENTS_PAYLOAD, text_length=10)
    return dream, scenes.create_scenes(db, dream.id, SCENES)


def test_set_appearances_only_on_person_element(db, dream_with_scenes):
    dream, _ = dream_with_scenes
    updated = extractions.set_character_appearances(db, dream.id, [GRANDMA])
    assert [(e.name, e.name_en, e.appearance_en) for e in updated] == [
        ("할머니", "the grandmother", "short white hair, pink cardigan")
    ]
    others = [e for e in extractions.list_elements(db, dream.id) if e.name != "할머니"]
    assert all(e.name_en is None and e.appearance_en == "" for e in others)


def test_scene_characters_for_payload(db, dream_with_scenes):
    dream, created = dream_with_scenes
    extractions.set_character_appearances(db, dream.id, [GRANDMA])

    with_grandma = created[1].current_version_id  # 장면 2: 할머니, 우산
    assert scenes.list_scene_characters(db, with_grandma) == [
        {"name": "the grandmother", "appearance": "short white hair, pink cardigan"}
    ]
    assert scenes.list_scene_characters(db, created[0].current_version_id) == []  # 인물 없는 장면
    assert scenes.list_scene_characters(db, 999_999_999) is None


def test_revised_version_reads_same_appearance(db, dream_with_scenes):
    """재시도·수정으로 새 버전을 만들어도 같은 인물은 같은 문구 (인물 일관성)."""
    dream, created = dream_with_scenes
    extractions.set_character_appearances(db, dream.id, [GRANDMA])
    v1 = created[1].current_version
    v2 = scenes.add_scene_version(db, created[1].id, summary_ko="수정", prompt_en="p2", element_ids=v1.element_ids)
    assert scenes.list_scene_characters(db, v2.id) == scenes.list_scene_characters(db, v1.id)


def test_before_saving_appearances_is_empty(db, dream_with_scenes):
    _, created = dream_with_scenes
    assert scenes.list_scene_characters(db, created[1].current_version_id) == []


def test_missing_appearance_is_empty_string(db, dream_with_scenes):
    dream, created = dream_with_scenes
    extractions.set_character_appearances(db, dream.id, [{"name": "할머니", "name_en": "the grandmother"}])
    assert scenes.list_scene_characters(db, created[1].current_version_id) == [
        {"name": "the grandmother", "appearance": ""}
    ]


def test_calling_again_overwrites(db, dream_with_scenes):
    dream, created = dream_with_scenes
    extractions.set_character_appearances(db, dream.id, [GRANDMA])
    extractions.set_character_appearances(db, dream.id, [{**GRANDMA, "appearance_en": "round glasses"}])
    assert scenes.list_scene_characters(db, created[1].current_version_id)[0]["appearance"] == "round glasses"


@pytest.mark.parametrize(
    "bad",
    [
        [{"name": "우산", "name_en": "umbrella"}],  # 인물이 아닌 요소
        [{"name": "없는사람", "name_en": "nobody"}],
        [{"name": "할머니", "name_en": "  "}],
    ],
)
def test_invalid_characters_change_nothing(db, dream_with_scenes, bad):
    dream, created = dream_with_scenes
    with pytest.raises(InvalidData):
        extractions.set_character_appearances(db, dream.id, [GRANDMA, *bad])
    assert scenes.list_scene_characters(db, created[1].current_version_id) == []
