"""repositories 테스트 공용 도우미."""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Dream

ELEMENTS_PAYLOAD = {
    "elements": [
        {"type": "place", "name": "학교 복도", "description": "형광등이 깜빡이는 어두운 복도"},
        {"type": "person", "name": "할머니", "description": "분홍색 카디건"},
        {"type": "object", "name": "우산", "description": "노란 장우산"},
        {"type": "emotion", "name": "두려움", "description": ""},
    ],
    "questions": [],
}

SCENES = [
    {"order": 1, "summary_ko": "복도를 걷는다.", "element_names": ["학교 복도", "두려움"], "image_prompt_en": "hallway"},
    {"order": 2, "summary_ko": "할머니가 우산을 건넨다.", "element_names": ["할머니", "우산", "없는요소"], "image_prompt_en": "grandma"},
    {"order": 3, "summary_ko": "창밖은 바다다.", "element_names": [], "image_prompt_en": "sea"},
]


@contextmanager
def committed_dream(engine: Engine, **kw) -> Iterator[int]:
    """여러 연결에서 보이도록 실제로 commit한 꿈 기록을 만들고, 끝나면 지운다 (동시성 테스트용)."""
    with Session(engine) as s:
        dream = Dream(input_type="text", raw_text="동시성", **kw)
        s.add(dream)
        s.commit()
        dream_id = dream.id
    try:
        yield dream_id
    finally:
        with Session(engine) as s:
            s.query(Dream).filter_by(id=dream_id).delete()
            s.commit()


def run_concurrently(engine: Engine, fn: Callable[[Session], object], n: int = 2) -> list[object]:
    """n개 연결에서 fn(session)을 동시에 시작해 각각 commit하고 결과를 모은다."""
    barrier = threading.Barrier(n)
    results: list[object] = [None] * n
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            with Session(engine) as s:
                barrier.wait()
                results[i] = fn(s)
                s.commit()
        except BaseException as exc:  # noqa: BLE001 - 테스트에서 그대로 다시 던진다
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    if errors:
        raise errors[0]
    return results
