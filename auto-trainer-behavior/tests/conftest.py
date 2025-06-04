from typing import List, Any

import pytest

from autotrainer.core import EventManager
from autotrainer.core import ProjectInfo

@pytest.fixture(autouse=True)
def _auto_close_event_manager():
    # allow to close the EventManager and have its worker thread exits gracefully (on each end of test case)
    yield
    mgr = getattr(EventManager, "_instance", None)
    if mgr is not None:
        assert isinstance(mgr, EventManager)
        mgr.close()
        del EventManager._instance  # noqa


def on_state_changed(old_value, new_value, *, state_transitions: List[Any]):
    """Helper to record the transitions of state (although it could be any property/attribute)
    Also ensure/assert that the transitions are consistent.
    """
    if len(state_transitions) > 0:
        assert state_transitions[-1] == old_value
    state_transitions.append(new_value)


@pytest.fixture
def project_info(tmp_path):
    root = tmp_path.joinpath("root")
    root.mkdir()
    prj = ProjectInfo(root=root.as_posix())
    yield prj
