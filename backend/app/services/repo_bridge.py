# TODO(DB 담당): repositories로 교체 (my-docs/requests.md 요청: update_raw_text, get_latest_extraction)
"""repositories에 아직 없는 함수를 요청한 이름·시그니처 그대로 실제 DB 세션으로 구현한다.

모델 직접 사용은 이 파일 안에서만 허용한다. repositories 약속과 같게 commit하지 않고 flush까지만 한다.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dream, Extraction


def update_raw_text(db: Session, dream_id: int, raw_text: str) -> Dream | None:
    """STT 변환 텍스트를 raw_text에 저장한다. 꿈 기록이 없으면 None."""
    dream = db.get(Dream, dream_id)
    if dream is None:
        return None
    dream.raw_text = raw_text
    db.flush()
    return dream


def get_latest_extraction(db: Session, dream_id: int) -> Extraction | None:
    """가장 최근 추출 1행. 없으면 None. 순서는 repositories.extractions.list_elements와 같다."""
    return db.scalar(
        select(Extraction)
        .where(Extraction.dream_id == dream_id)
        .order_by(Extraction.created_at.desc(), Extraction.id.desc())
        .limit(1)
    )
