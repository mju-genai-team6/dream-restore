"""D의 장면 수정 함수 연결.

TODO(D): app.llm이 revise_scene을 내보내면 이 파일을 고치지 않고 그 함수를 쓴다.
가짜 구현은 두지 않는다. 테스트는 monkeypatch로만 넣는다.
"""

try:
    from app.llm import revise_scene
except ImportError:
    revise_scene = None
