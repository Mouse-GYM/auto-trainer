import math
from typing import Protocol, List, Dict, Any, Optional
import copy

from autotrainer.core import Motor
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


def validate_int_float(value):
    if isinstance(value, str):
        f_value = float(value)
        if f_value.is_integer() and "." not in value:
            value = int(f_value)
        else:
            value = f_value
    elif not isinstance(value, (int, float)):
        raise ValueError(f"Invalid value for int/float: {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"Not finite value not accepted: {value!r}")
    return value


def validate_stepper(value):
    orig_value = value
    if isinstance(orig_value, str):
        value = getattr(Motor, orig_value, None)
        if not isinstance(value, Motor):
            value = Motor(int(orig_value))
    if value not in {Motor.PELLET_X_MOTOR, Motor.PELLET_Y_MOTOR, Motor.PELLET_Z_MOTOR}:
        raise ValueError(f"Invalid value for stepper: {orig_value!r}")
    return value


def validate_servo(value):
    if isinstance(value, str):
        attr_val = getattr(Motor, value, None)  # allow reference by full enum member name too
        if isinstance(attr_val, Motor):
            value = attr_val
        else:
            value = Motor(int(value))
    if value not in {
        Motor.TUNNEL_MAGNET_SERVO,
        Motor.TUNNEL_GATE_SERVO,
        Motor.TUNNEL_FAN_SERVO,
        Motor.PELLET_COVER_SERVO,
        Motor.PELLET_LOAD_SERVO,
    }:
        raise ValueError(f"Invalid value for servo: {value!r}")
    return value


def validate_position_or_pos_velocity(value):
    if isinstance(value, str):
        if "," in value:
            pos, vel = value.split(',')
            return validate_int_float(pos), validate_int_float(vel)
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        return validate_int_float(value[0]), validate_int_float(value[1])
    return validate_int_float(value)


def validate_predefined(value):
    if value not in {
        "home",
        "send",
        "cover",
        "release",
        "retrieve",
        "scoop",  # NB: unused
    }:
        raise ValueError(f"Invalid value for predefined: {value!r}")
    return value


def validate_servo_move(value):
    if isinstance(value, str):
        servo, pos_or_vel = value.split(",", 1)
    else:
        servo, pos_or_vel = value
    servo = validate_servo(servo)
    pos_or_vel = validate_position_or_pos_velocity(pos_or_vel)
    return servo, pos_or_vel


def validate_tone(value):
    if isinstance(value, str):
        freq, duration = value.split(",")
        freq = int(freq)
    else:
        freq, duration = value
    if not isinstance(freq, int):
        raise ValueError(f"Invalid value for tone freq: {freq} ; val={value}")
    return freq, validate_int_float(duration)


def validate_extra_data(dct: Dict[str, Any]):
    tp = dct["type"]
    accept_uuid_ack_timeout = tp in {
        "x", "y", "z", "x_rel", "y_rel", "z_rel", "send_x_rel", "send_y_rel", "send_z_rel",
        "predefined", "home", "gate", "magnet", "load_arm", "barrier_arm",
        "_servo_move", "_servo_min_pos", "_servo_max_pos",
    }
    for key, value in dct.items():
        if key in ("type", "value"):
            continue
        # at the moment we only support uuid_ack_timeout as eventual extra data
        if accept_uuid_ack_timeout and key == "uuid_ack_timeout":
            dct[key] = validate_int_float(value)
        else:
            raise ValueError(f"Unhandled extra data key {key}")


_compound_steps_validate = dict(
    delay=validate_int_float,
    tone=validate_tone,
    x=validate_position_or_pos_velocity,
    y=validate_position_or_pos_velocity,
    z=validate_position_or_pos_velocity,
    send_x_rel=validate_int_float,
    send_y_rel=validate_int_float,
    send_z_rel=validate_int_float,
    x_rel=validate_int_float,
    y_rel=validate_int_float,
    z_rel=validate_int_float,
    predefined=validate_predefined,
    home=validate_stepper,
    gate=validate_position_or_pos_velocity,
    magnet=validate_position_or_pos_velocity,
    load_arm=validate_position_or_pos_velocity,
    barrier_arm=validate_position_or_pos_velocity,
    _servo_move=validate_servo_move,
    servo_attach=validate_servo,
    servo_detach=validate_servo,
    _servo_min_pos=validate_servo,
    _servo_max_pos=validate_servo,
)


class MotorSteps:

    @classmethod
    def from_raw(cls, name: str, data: List[Dict[str, Any]]):
        steps = []
        for step in data:
            if not isinstance(step, dict):
                raise TypeError(f"Invalid type for a step: {type(step)}. step={step}")
            dct = copy.deepcopy(step)
            step_type: Optional[str] = dct.get('type', None)
            step_value = dct.get('value', None)
            if step_type is None or step_value is None:
                raise ValueError(f"Missing 'type' or 'value' key for motor steps, got {step}")
            validate = _compound_steps_validate.get(step_type, None)
            if validate is None:
                raise ValueError(f"Unhandled step type: {step_type!r} in {step}")
            step_value = validate(step_value)
            dct['value'] = step_value
            validate_extra_data(dct)
            steps.append(dct)
        if len(steps) == 0:
            raise ValueError(f"Empty steps for MotorSteps {name}. You can set the action to null to no-op it.")
        return MotorSteps(name, steps)

    def __init__(self, name: str = "NA", steps: Optional[List[Dict[str, Any]]] = None):
        self._name = name
        self._steps = steps

    def __repr__(self):
        return f"MotorSteps(name={self._name!r}, steps={self._steps})"

    @property
    def name(self) -> str:
        return self._name

    @property
    def steps(self):
        return self._steps

    @property
    def is_empty(self):
        return self._steps is None or len(self._steps) == 0


class CompoundMovementDataSet(Protocol):

    @property
    def load_pellet(self) -> MotorSteps:
        """The load pellet procedure"""

    @property
    def send_pellet(self) -> MotorSteps:
        """The send pellet procedure"""

    @property
    def cover_pellet(self) -> MotorSteps:
        """The cover pellet procedure"""

    @property
    def release_pellet(self) -> MotorSteps:
        """The release pellet procedure"""

    @property
    def open_tunnel_gate(self) -> MotorSteps:
        """The open tunnel gate procedure"""

    @property
    def close_tunnel_gate(self) -> MotorSteps:
        """The close tunnel gate procedure"""

    @property
    def move_retract(self) -> MotorSteps:
        """The move retract procedure"""
