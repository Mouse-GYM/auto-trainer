import logging

from autotrainer.behavior import BehaviorAlgorithm, BehaviorLimits, IntersessionMachine, IntersessionState

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_intersession_transitions():
    """Tests transition behavior with explicit calls to the transitions"""
    algorithm = BehaviorAlgorithm(BehaviorLimits())

    model = IntersessionMachine(algorithm, None)

    assert model.state == IntersessionState.idle

    model.perform_segmentation()

    assert model.state == IntersessionState.segmentation

    model.perform_detection()

    assert model.state == IntersessionState.detection

    model.end_analysis()

    assert model.state == IntersessionState.idle


if __name__ == '__main__':
    test_intersession_transitions()
