"""evaluation kind check

evaluations.kind 값을 지표 뷰가 읽는 두 가지로 제한한다.
- confidence: E1 확신도 표현 평가 (v_confidence_evaluation)
- character: E2 인물 일관성 평가 (v_character_consistency)
다른 값으로 저장하면 뷰에서 빠지므로 저장 단계에서 막는다.

Revision ID: b3e1d2c4a5f6
Revises: 5ccb1fbaa197
Create Date: 2026-11-16 20:00:00.000000
"""
from alembic import op

revision = 'b3e1d2c4a5f6'
down_revision = '5ccb1fbaa197'
branch_labels = None
depends_on = None

# app/models/world.py의 EVALUATION_KINDS와 같아야 한다
KINDS = ('confidence', 'character')


def upgrade() -> None:
    values = ', '.join(f"'{k}'" for k in KINDS)
    op.create_check_constraint(op.f('ck_evaluations_kind'), 'evaluations', f'kind IN ({values})')


def downgrade() -> None:
    op.drop_constraint(op.f('ck_evaluations_kind'), 'evaluations', type_='check')
