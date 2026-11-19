"""add dream_elements name_en, appearance_en

인물 요소의 이미지용 영어 이름·외형 (C 요청).
장면 생성 때 D 결과의 characters를 저장해 두고, 이미지 재시도·장면 수정 때 다시 읽는다.

Revision ID: c7d4e9a1b2f3
Revises: b3e1d2c4a5f6
Create Date: 2026-11-19 20:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'c7d4e9a1b2f3'
down_revision = 'b3e1d2c4a5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('dream_elements', sa.Column('name_en', sa.String(length=50), nullable=True))
    op.add_column('dream_elements', sa.Column('appearance_en', sa.Text(), server_default='', nullable=False))


def downgrade() -> None:
    op.drop_column('dream_elements', 'appearance_en')
    op.drop_column('dream_elements', 'name_en')
