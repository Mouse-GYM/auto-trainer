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

@pytest.mark.parametrize("bad_actions", [
    "foobar", [], (), None, 32,
])
def test_invalid_actions_type(bad_actions):
    dct = dict(actions=bad_actions)
    with pytest.raises(TypeError):
        CompoundMovements.from_yaml_dict(dct)


@pytest.mark.parametrize("invalid_key", ["unknown1", 30])
def test_invalid_top_key(invalid_key):
    dct = dict(actions={})
    dct[invalid_key] = "anything"  # noqa
    with pytest.raises(ValueError):
        CompoundMovements.from_yaml_dict(dct)


def test_multiple_data_in_steps():
    open_gate_steps = [
        dict(type="_servo_min_pos", value=Motor.TUNNEL_GATE_SERVO.value, uuid_ack_timeout=8),
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


def test_unhandled_extra_data_raise():
    with pytest.raises(ValueError, match="Unhandled extra data key"):
        MotorSteps.from_raw("name", [dict(type="x", value=0, invalid_extra="anything")])


@pytest.mark.parametrize("step,data", [
    ("delay", 1),
    ("tone", (3000, 0.5))
])
def test_uuid_ack_timeout_rejected(step, data):
    dct = dict(type=step, value=data)
    dct["uuid_ack_timeout"] = 1
    with pytest.raises(ValueError, match="Unhandled extra data key"):
        MotorSteps.from_raw("name", [dct])
    # but
    del dct["uuid_ack_timeout"]
    assert MotorSteps.from_raw("name", [dct]).steps == [dct]


@pytest.mark.parametrize("step,data", [
    ("x", 0),
    ("send_x_rel", 0),
    ("predefined", "home"),
    ("_servo_min_pos", Motor.TUNNEL_GATE_SERVO),
    ("_servo_move", (Motor.TUNNEL_GATE_SERVO, 5)),
])
def test_uuid_ack_timeout_accepted(step, data):
    dct = dict(type=step, value=data, uuid_ack_timeout=15)
    steps = MotorSteps.from_raw("name", [dct])
    assert steps.steps == [dct]
