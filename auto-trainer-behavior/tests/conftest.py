from typing import List, Any

import pytest

from autotrainer.core import EventManager


# see remark in top-level conftest.py
@pytest.fixture(autouse=True)
def _event_manager():
    # allow to close the EventManager and have its worker thread exits gracefully (on each end of test case)
    yield
    mgr = EventManager.default()
    mgr.close()
    del EventManager._instance  # noqa


def on_state_changed(old_value, new_value, *, state_transitions: List[Any]):
    """Helper to record the transitions of state (although it could be any property/attribute)
    Also ensure/assert that the transitions are consistent.
    """
    if len(state_transitions) > 0:
        assert state_transitions[-1] == old_value
    state_transitions.append(new_value)
