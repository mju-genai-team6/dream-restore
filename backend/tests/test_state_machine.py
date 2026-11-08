import pytest

from app.core.enums import DreamStatus
from app.core.errors import InvalidState
from app.services.state_machine import ensure_transition


def test_forward_transition_allowed():
    ensure_transition(DreamStatus.RECORDED, DreamStatus.INTERVIEWING)


def test_skip_transition_blocked():
    with pytest.raises(InvalidState):
        ensure_transition(DreamStatus.RECORDED, DreamStatus.RENDERED)
