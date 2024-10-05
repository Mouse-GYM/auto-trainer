import logging

from autotrainer.behavior import BehaviorModel, SystemStates, PelletDeliveryStates

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_default_transitions():
    """Tests transition behavior with explicit calls to the transitions"""
    model = BehaviorModel(None, None, None, None)

    assert model.state == SystemStates.cage

    model.enter_tunnel()

    assert model.state == PelletDeliveryStates.monitoring

    model.my_load_pellet()

    assert model.state == PelletDeliveryStates.loading

    model.send_pellet()

    assert model.state == PelletDeliveryStates.sending

    model.release_pellet()

    assert model.state == PelletDeliveryStates.releasing

    model.monitor_pellet()

    assert model.state == PelletDeliveryStates.monitoring

    model.exit_tunnel()

    assert model.state == SystemStates.cage


if __name__ == '__main__':
    test_default_transitions()
