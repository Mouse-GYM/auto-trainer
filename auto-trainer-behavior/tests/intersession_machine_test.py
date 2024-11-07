import logging

import pytest
from transitions import MachineError

from autotrainer.behavior import IntersessionState

from mocks import BehaviorMachineWithMocks

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_intersession():
    machine = BehaviorMachineWithMocks()

    intersession = machine.intersession

    assert intersession.state == IntersessionState.idle

    with pytest.raises(MachineError):
        intersession.perform_detection()

    intersession.perform_segmentation()

    assert intersession.state == IntersessionState.segmentation

    machine.mock_inference.mock_complete_segmentation(True)

    assert intersession.state == IntersessionState.detection

    machine.mock_inference.mock_complete_detection(True)

    assert intersession.state == IntersessionState.idle


if __name__ == '__main__':
    test_intersession()
