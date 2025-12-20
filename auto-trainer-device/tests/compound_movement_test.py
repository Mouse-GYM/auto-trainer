from autotrainer.device import CompoundMovements, MotorSteps


def test_can_load():
    movements = CompoundMovements.from_file(CompoundMovements.DEFAULT_LOCATION)
    assert isinstance(movements, CompoundMovements)
    assert isinstance(movements.load_pellet, MotorSteps)
    assert isinstance(movements.send_pellet, MotorSteps)
    assert isinstance(movements.cover_pellet, MotorSteps)
    assert isinstance(movements.release_pellet, MotorSteps)
