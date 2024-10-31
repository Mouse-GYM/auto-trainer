import logging

from autotrainer.behavior import BehaviorAlgorithm, BehaviorLimits, IntersessionMachine, IntersessionState

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_intersession_transitions():
    """Tests transition behavior with explicit calls to the transitions"""
    algorithm = BehaviorAlgorithm(BehaviorLimits())

    machine = IntersessionMachine(algorithm, None)

    assert machine.state == IntersessionState.idle

    machine.perform_segmentation()

    assert machine.state == IntersessionState.segmentation

    machine.perform_detection()

    assert machine.state == IntersessionState.detection

    machine.end_analysis()

    assert machine.state == IntersessionState.idle


if __name__ == '__main__':
    test_intersession_transitions()
