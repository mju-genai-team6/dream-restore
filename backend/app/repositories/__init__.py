"""데이터 접근 함수 (C2). C는 이 함수만 호출하고 테이블을 직접 조회하지 않는다.

공통 규칙
- 첫 인자는 DB 세션. **commit하지 않는다.** 확정(commit)·취소(rollback)는 C의 services에서 한다.
  새로 만든 행의 id가 필요하므로 flush는 한다.
- 반환은 ORM 객체(app/models). 없으면 None. 테이블 한 행이 아닌 값만 예외로 NamedTuple·bool·int.
- 저장 형식(요소·질문·장면)은 D의 LLM 출력(app/llm/schemas.py)을 model_dump()한 dict 그대로 받는다.
- 규칙 위반(다른 꿈의 요소, 잘못된 확신도 값 등)은 InvalidData를 던지고 아무것도 바꾸지 않는다.

컬럼 설명은 docs/rules/data-model.md.
"""


class InvalidData(ValueError):
    """저장하려는 값이 규칙에 맞지 않음. C는 400 VALIDATION_ERROR로 바꾼다."""

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}
