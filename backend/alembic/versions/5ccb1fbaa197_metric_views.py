"""metric views

DB 이관 문서 6장: 검증 지표를 SQL 한 번(SELECT * FROM 뷰)으로 꺼낼 수 있는 조회용 뷰 4개.
설명은 docs/rules/data-model.md "지표 뷰".

Revision ID: 5ccb1fbaa197
Revises: f9772c262e42
Create Date: 2026-11-16 15:57:06.844464
"""
from alembic import op

revision = '5ccb1fbaa197'
down_revision = 'f9772c262e42'
branch_labels = None
depends_on = None

# evaluations.kind 값. E1·E2와 확정되면 같이 바꾼다
CONFIDENCE_KIND = 'confidence'  # E1 확신도 표현 평가
CHARACTER_KIND = 'character'  # E2 인물 일관성 평가
RECOGNIZED_MIN_SCORE = 4  # 이 점수 이상이면 "같은 인물로 인식"

VIEWS = {
    # D: 꿈별 원문 추출(raw)과 인터뷰 반영 추출(after_interview)의 요소 수·글자 수 비교
    'v_interview_comparison': """
        WITH latest AS (
            SELECT DISTINCT ON (dream_id, phase) dream_id, phase, element_count, text_length
            FROM extractions
            ORDER BY dream_id, phase, created_at DESC, id DESC
        )
        SELECT d.id AS dream_id,
               d.created_at,
               r.element_count AS raw_element_count,
               a.element_count AS after_element_count,
               a.element_count - r.element_count AS element_increase,
               r.text_length AS raw_text_length,
               a.text_length AS after_text_length,
               a.text_length - r.text_length AS text_length_increase
        FROM dreams d
        JOIN latest r ON r.dream_id = d.id AND r.phase = 'raw'
        LEFT JOIN latest a ON a.dream_id = d.id AND a.phase = 'after_interview'
    """,
    # E1: 조건별 확신도 표현 평가(1~5점) 평균과 응답 수
    'v_confidence_evaluation': f"""
        SELECT condition,
               count(*) AS response_count,
               round(avg(score), 2) AS avg_score
        FROM evaluations
        WHERE kind = '{CONFIDENCE_KIND}'
        GROUP BY condition
    """,
    # E2: 조건별 같은 인물로 인식한 비율 (점수 RECOGNIZED_MIN_SCORE 이상을 인식으로 봄)
    'v_character_consistency': f"""
        SELECT condition,
               count(*) AS response_count,
               count(*) FILTER (WHERE score >= {RECOGNIZED_MIN_SCORE}) AS recognized_count,
               round(avg((score >= {RECOGNIZED_MIN_SCORE})::int), 3) AS recognized_ratio,
               round(avg(score), 2) AS avg_score
        FROM evaluations
        WHERE kind = '{CHARACTER_KIND}'
        GROUP BY condition
    """,
    # C·전원: 꿈별 처리 시간(초). 성공한 작업 기준
    #   장면 분할: 마지막으로 성공한 generate_scenes의 실행 시간
    #   이미지 생성: 성공한 generate_image 중 가장 먼저 시작~가장 늦게 끝난 시간(장면 병렬 처리 포함 체감 시간)
    #   렌더링: 마지막으로 성공한 render_video의 실행 시간
    'v_processing_time': """
        SELECT d.id AS dream_id,
               d.created_at,
               s.seconds AS scene_split_seconds,
               i.seconds AS image_gen_seconds,
               i.job_count AS image_job_count,
               r.seconds AS render_seconds
        FROM dreams d
        LEFT JOIN LATERAL (
            SELECT extract(epoch FROM finished_at - started_at) AS seconds
            FROM jobs
            WHERE dream_id = d.id AND type = 'generate_scenes' AND status = 'succeeded'
            ORDER BY finished_at DESC
            LIMIT 1
        ) s ON true
        LEFT JOIN LATERAL (
            SELECT extract(epoch FROM max(finished_at) - min(started_at)) AS seconds, count(*) AS job_count
            FROM jobs
            WHERE dream_id = d.id AND type = 'generate_image' AND status = 'succeeded'
        ) i ON true
        LEFT JOIN LATERAL (
            SELECT extract(epoch FROM finished_at - started_at) AS seconds
            FROM jobs
            WHERE dream_id = d.id AND type = 'render_video' AND status = 'succeeded'
            ORDER BY finished_at DESC
            LIMIT 1
        ) r ON true
        WHERE EXISTS (SELECT 1 FROM jobs WHERE dream_id = d.id AND status = 'succeeded')
    """,
}


def upgrade() -> None:
    for name, sql in VIEWS.items():
        op.execute(f'CREATE VIEW {name} AS {sql}')


def downgrade() -> None:
    for name in reversed(VIEWS):
        op.execute(f'DROP VIEW {name}')
