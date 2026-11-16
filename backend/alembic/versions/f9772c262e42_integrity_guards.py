"""integrity guards

DB 이관 문서 5장 무결성 규칙을 DB에서 지킨다.
- 장면 버전은 추가만: scene_versions의 내용 컬럼 수정 금지, 이미지 생성 결과는 비어 있을 때 한 번만 채움
- 영상의 장면 버전 고정: renders.scene_version_ids 수정 금지
- 파일과 기록 구분: 경로 컬럼은 storage/ 기준 상대 경로만 허용

위반하면 SQLSTATE 23000(integrity_constraint_violation) → SQLAlchemy IntegrityError.

Revision ID: f9772c262e42
Revises: 8a9b61da1f4c
Create Date: 2026-11-16 15:48:01.698583
"""
from alembic import op

revision = 'f9772c262e42'
down_revision = '8a9b61da1f4c'
branch_labels = None
depends_on = None

# (테이블, 컬럼) — 모델의 relative_path_check와 같아야 한다
PATH_COLUMNS = [
    ('audio_files', 'path'),
    ('scene_versions', 'image_path'),
    ('renders', 'video_path'),
    ('narrations', 'audio_path'),
]


def _path_check_sql(column: str) -> str:
    return f"{column} !~ '^[/\\\\]' AND {column} !~ '^[A-Za-z]:' AND {column} NOT LIKE '%..%'"


SCENE_VERSIONS_GUARD = """
CREATE FUNCTION scene_versions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- 내용은 바꿀 수 없다 (수정은 새 버전 행으로)
    IF NEW.scene_id IS DISTINCT FROM OLD.scene_id
       OR NEW.version_no IS DISTINCT FROM OLD.version_no
       OR NEW.summary_ko IS DISTINCT FROM OLD.summary_ko
       OR NEW.prompt_en IS DISTINCT FROM OLD.prompt_en
       OR NEW.element_ids IS DISTINCT FROM OLD.element_ids THEN
        RAISE EXCEPTION 'scene_versions % 의 내용은 바꿀 수 없습니다. 새 버전을 추가하세요.', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- 이미지 생성 결과·장면 확신도는 비어 있을 때 한 번만 채운다
    IF (OLD.final_prompt IS NOT NULL AND NEW.final_prompt IS DISTINCT FROM OLD.final_prompt)
       OR (OLD.model IS NOT NULL AND NEW.model IS DISTINCT FROM OLD.model)
       OR (OLD.seed IS NOT NULL AND NEW.seed IS DISTINCT FROM OLD.seed)
       OR (OLD.image_path IS NOT NULL AND NEW.image_path IS DISTINCT FROM OLD.image_path)
       OR (OLD.generated_at IS NOT NULL AND NEW.generated_at IS DISTINCT FROM OLD.generated_at)
       OR (OLD.confidence_level IS NOT NULL AND NEW.confidence_level IS DISTINCT FROM OLD.confidence_level)
       OR (OLD.settings <> '{}'::jsonb AND NEW.settings IS DISTINCT FROM OLD.settings) THEN
        RAISE EXCEPTION 'scene_versions % 의 생성 결과는 이미 저장되어 바꿀 수 없습니다.', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;
CREATE TRIGGER scene_versions_guard BEFORE UPDATE ON scene_versions
    FOR EACH ROW EXECUTE FUNCTION scene_versions_guard();
"""

RENDERS_GUARD = """
CREATE FUNCTION renders_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.scene_version_ids IS DISTINCT FROM OLD.scene_version_ids THEN
        RAISE EXCEPTION 'renders % 의 장면 버전 목록은 바꿀 수 없습니다.', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER renders_guard BEFORE UPDATE ON renders
    FOR EACH ROW EXECUTE FUNCTION renders_guard();
"""


def upgrade() -> None:
    for table, column in PATH_COLUMNS:
        op.create_check_constraint(op.f(f'ck_{table}_{column}_relative'), table, _path_check_sql(column))
    op.execute(SCENE_VERSIONS_GUARD)
    op.execute(RENDERS_GUARD)


def downgrade() -> None:
    op.execute('DROP TRIGGER renders_guard ON renders')
    op.execute('DROP FUNCTION renders_guard()')
    op.execute('DROP TRIGGER scene_versions_guard ON scene_versions')
    op.execute('DROP FUNCTION scene_versions_guard()')
    for table, column in reversed(PATH_COLUMNS):
        op.drop_constraint(op.f(f'ck_{table}_{column}_relative'), table, type_='check')
