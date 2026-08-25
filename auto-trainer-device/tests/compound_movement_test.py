import pytest

from autotrainer.core import Motor
from autotrainer.device import CompoundMovements, MotorSteps
from autotrainer.device.can_device import mk_step
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



@pytest.mark.parametrize("step,xp", [
    (mk_step("x", "3.3"), mk_step("x", 3.3)),
    (mk_step("x", (1.1,2.2)), mk_step("x", (1.1, 2.2))),
    (mk_step("x", "1.1,2.2"), mk_step("x", (1.1, 2.2))),
    (mk_step("gate", (1.1,2.2)), mk_step("gate", (1.1, 2.2))),
    (mk_step("home", f"{Motor.PELLET_Y_MOTOR.value}"), mk_step("home", Motor.PELLET_Y_MOTOR)),
    (mk_step("home", "PELLET_X_MOTOR"), mk_step("home", Motor.PELLET_X_MOTOR)),
    (mk_step("send_z_rel", "-15"), mk_step("send_z_rel", -15)),
    (mk_step("x_rel", "-15"), mk_step("x_rel", -15)),
    (mk_step("predefined", "retrieve"), mk_step("predefined", "retrieve")),
    (mk_step("_servo_move", "TUNNEL_MAGNET_SERVO,5"), mk_step("_servo_move", (Motor.TUNNEL_MAGNET_SERVO, 5))),
    # _servo_move with (pos, velo):
    (mk_step("_servo_move", "TUNNEL_MAGNET_SERVO,5,3"), mk_step("_servo_move", (Motor.TUNNEL_MAGNET_SERVO, (5, 3)))),
])
def test_valid_steps(step, xp):
    m_steps = MotorSteps.from_raw("foobar", [step])
    assert m_steps.steps == [xp]


@pytest.mark.parametrize("step", [
    mk_step("step_does_not_exist", 0),
    mk_step("delay", "bad"),
    mk_step("predefined", "unknown"),
    mk_step("x", "0,1,2"),  # too many
    mk_step("send_x_rel", "0,1"),  # don't accept pos+velo
    mk_step("x_rel", "-15,2.2"),  # don't accept pos+velo
    mk_step("x_rel", (-15, 2.2)),
    mk_step("tone", (3.3, 2)),  # freq must be int
    mk_step("tone", (300, "bad")),  # bad duration
])
def test_invalid_step_raise(step):
    with pytest.raises((ValueError, TypeError)):
        MotorSteps.from_raw("some_compound", [step])
