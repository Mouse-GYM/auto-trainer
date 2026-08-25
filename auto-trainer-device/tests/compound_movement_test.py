from autotrainer.core import Motor
from autotrainer.device import CompoundMovements, MotorSteps
from autotrainer.device.compound_movement_file import CompoundMovementKind


def test_load_from_default():
    movements = CompoundMovements.from_file(CompoundMovements.DEFAULT_LOCATION)
    for kind in CompoundMovementKind:
        move_steps = getattr(movements, kind.value)
        assert isinstance(move_steps, MotorSteps)
        assert move_steps.name == kind.value


def test_multiple_data_in_steps():
    open_gate_steps = [
        dict(type="_servo_min_pos", value=Motor.TUNNEL_GATE_SERVO.value, foobar=42),
    ]
    actions = dict(open_tunnel_gate=open_gate_steps)
    movements = CompoundMovements.from_yaml_dict(
        dict(actions=actions)
    )
    assert isinstance(movements, CompoundMovements)
    open_gate = movements.open_tunnel_gate
    assert isinstance(open_gate, MotorSteps)
    assert len(open_gate.steps) == 1
    assert open_gate.name == "open_tunnel_gate"
    assert open_gate.steps == open_gate_steps
