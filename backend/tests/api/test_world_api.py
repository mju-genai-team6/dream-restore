"""세계관 인물·장소 등록 API (S4)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PERSON = {
    "name": "  할머니  ",
    "kind": "person",
    "age_range": " elderly ",
    "hair": "short white hair",
    "outfit": "분홍색 카디건",
    "features": "왼쪽 볼의 점",
}


def test_create_list_get_patch_and_kind_filter():
    created = client.post("/world/entities", json=PERSON)
    assert created.status_code == 201, created.text
    assert "X-Mock" not in created.headers
    body = created.json()
    assert set(body) == {"id", "kind", "name", "age_range", "hair", "outfit", "features", "created_at"}
    assert body["name"] == "할머니"
    assert body["kind"] == "person"
    assert body["age_range"] == "elderly"
    assert body["hair"] == "short white hair"
    assert body["outfit"] == "분홍색 카디건"
    assert body["features"] == "왼쪽 볼의 점"
    entity_id = body["id"]

    place = client.post("/world/entities", json={"name": "학교", "kind": "place", "features": "  "})
    assert place.status_code == 201, place.text
    assert place.json()["features"] is None
    place_id = place.json()["id"]

    listed = client.get("/world/entities")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["entities"]] == [entity_id, place_id]

    people = client.get("/world/entities", params={"kind": "person"})
    assert [item["id"] for item in people.json()["entities"]] == [entity_id]

    fetched = client.get(f"/world/entities/{entity_id}")
    assert fetched.status_code == 200
    assert fetched.json() == body

    patched = client.patch(f"/world/entities/{entity_id}", json={"outfit": "노란 우산"})
    assert patched.status_code == 200, patched.text
    updated = patched.json()
    assert updated["outfit"] == "노란 우산"
    assert updated["hair"] == "short white hair"
    assert updated["name"] == "할머니"
    assert updated["features"] == "왼쪽 볼의 점"

    cleared = client.patch(f"/world/entities/{entity_id}", json={"hair": ""})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["hair"] is None
    assert cleared.json()["outfit"] == "노란 우산"


def test_missing_entity_is_not_found():
    missing = client.get("/world/entities/999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"

    patched = client.patch("/world/entities/999", json={"name": "없음"})
    assert patched.status_code == 404
    assert patched.json()["error"]["code"] == "NOT_FOUND"


def test_empty_name_long_values_and_bad_kind_are_400():
    empty = client.post("/world/entities", json={"name": "", "kind": "person"})
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "VALIDATION_ERROR"
    blank = client.post("/world/entities", json={"name": "   ", "kind": "person"})
    assert blank.status_code == 400
    assert blank.json()["error"]["code"] == "VALIDATION_ERROR"

    assert client.post("/world/entities", json={"name": "가" * 51, "kind": "person"}).status_code == 400
    long_hair = {"name": "가", "kind": "person", "hair": "h" * 201}
    assert client.post("/world/entities", json=long_hair).status_code == 400
    long_outfit = {"name": "가", "kind": "person", "outfit": "o" * 201}
    assert client.post("/world/entities", json=long_outfit).status_code == 400
    long_age = {"name": "가", "kind": "person", "age_range": "a" * 51}
    assert client.post("/world/entities", json=long_age).status_code == 400

    bad_kind = client.post("/world/entities", json={"name": "가", "kind": "object"})
    assert bad_kind.status_code == 400
    assert bad_kind.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/world/entities", params={"kind": "emotion"}).status_code == 400

    created = client.post("/world/entities", json={"name": "가", "kind": "person"})
    assert created.status_code == 201, created.text
    entity_id = created.json()["id"]
    assert client.patch(f"/world/entities/{entity_id}", json={"name": "  "}).status_code == 400
    assert client.patch(f"/world/entities/{entity_id}", json={"name": None}).status_code == 400
    assert client.patch(f"/world/entities/{entity_id}", json={"kind": "animal"}).status_code == 400
    assert client.get(f"/world/entities/{entity_id}").json()["name"] == "가"


def test_duplicate_name_is_validation_error():
    first = client.post("/world/entities", json={"name": "엄마", "kind": "person"})
    assert first.status_code == 201, first.text
    dup = client.post("/world/entities", json={"name": " 엄마 ", "kind": "person"})
    assert dup.status_code == 400
    assert dup.json()["error"] == {
        "code": "VALIDATION_ERROR",
        "message": "같은 이름의 인물이 이미 있습니다.",
        "detail": {"field": "name", "reason": "duplicate", "existing_id": first.json()["id"]},
    }

    mom = client.post("/world/entities", json={"name": "Mom", "kind": "person"})
    assert mom.status_code == 201, mom.text
    case = client.post("/world/entities", json={"name": "mom", "kind": "person"})
    assert case.status_code == 400
    assert case.json()["error"]["code"] == "VALIDATION_ERROR"
    assert case.json()["error"]["detail"]["existing_id"] == mom.json()["id"]

    place = client.post("/world/entities", json={"name": "엄마", "kind": "place"})
    assert place.status_code == 201, place.text
    names = client.get("/world/entities").json()["entities"]
    assert [item["name"] for item in names] == ["엄마", "Mom", "엄마"]


def test_duplicate_place_name():
    first = client.post("/world/entities", json={"name": "학교", "kind": "place"})
    assert first.status_code == 201, first.text
    dup = client.post("/world/entities", json={"name": " 학교 ", "kind": "place"})
    assert dup.status_code == 400
    assert dup.json()["error"]["code"] == "VALIDATION_ERROR"
    assert dup.json()["error"]["message"] == "같은 이름의 장소가 이미 있습니다."
    assert dup.json()["error"]["detail"] == {
        "field": "name",
        "reason": "duplicate",
        "existing_id": first.json()["id"],
    }


def test_patch_name_conflict_and_same_name_ok():
    mom = client.post("/world/entities", json={"name": "엄마", "kind": "person"}).json()
    dad = client.post(
        "/world/entities", json={"name": "아빠", "kind": "person", "hair": "검은 머리"}
    ).json()

    conflict = client.patch(f"/world/entities/{dad['id']}", json={"name": " 엄마 "})
    assert conflict.status_code == 400
    assert conflict.json()["error"]["code"] == "VALIDATION_ERROR"
    assert conflict.json()["error"]["message"] == "같은 이름의 인물이 이미 있습니다."
    assert conflict.json()["error"]["detail"] == {
        "field": "name",
        "reason": "duplicate",
        "existing_id": mom["id"],
    }
    assert client.get(f"/world/entities/{dad['id']}").json()["name"] == "아빠"

    same = client.patch(
        f"/world/entities/{dad['id']}", json={"name": "아빠", "outfit": "회색 코트"}
    )
    assert same.status_code == 200, same.text
    assert same.json()["name"] == "아빠"
    assert same.json()["hair"] == "검은 머리"
    assert same.json()["outfit"] == "회색 코트"

    place = client.post("/world/entities", json={"name": "아빠", "kind": "place"}).json()
    kind_conflict = client.patch(f"/world/entities/{dad['id']}", json={"kind": "place"})
    assert kind_conflict.status_code == 400
    assert kind_conflict.json()["error"]["detail"]["existing_id"] == place["id"]
    assert client.get(f"/world/entities/{dad['id']}").json()["kind"] == "person"
