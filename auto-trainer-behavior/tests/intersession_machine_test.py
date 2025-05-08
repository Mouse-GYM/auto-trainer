import logging
from functools import partial

import pytest
from transitions import MachineError

from autotrainer.behavior import IntersessionState

from .mocks import BehaviorMachineWithMocks
from .conftest import on_state_changed

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_intersession():
    machine = BehaviorMachineWithMocks()

    intersession = machine.intersession
    state_transitions = []
    intersession.events.state_changed += partial(on_state_changed, state_transitions=state_transitions)

    assert intersession.state == IntersessionState.idle

    with pytest.raises(MachineError):
        intersession.perform_detection()

    intersession.perform_segmentation()
    assert intersession.state == IntersessionState.segmentation

    machine.mock_inference.mock_complete_segmentation(True)
    assert intersession.state == IntersessionState.detection

    machine.mock_inference.mock_complete_detection(True)
    assert intersession.state == IntersessionState.idle
    assert state_transitions == [
        IntersessionState.segmentation,
        IntersessionState.detection,
        IntersessionState.idle,
    ]


if __name__ == '__main__':
    test_intersession()
