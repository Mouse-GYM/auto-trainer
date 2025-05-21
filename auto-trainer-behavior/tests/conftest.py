from typing import List, Any

import pytest

from autotrainer.core import ProjectInfo


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
