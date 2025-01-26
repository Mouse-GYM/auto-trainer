import logging
import time
import typing
from dataclasses import dataclass

try:
    from pyjerrycan import JerryCAN, JerryCANMsg, JerryCANCmdType, JerryCANCfgMsg, AbsOrRel
except:
    pass

from .device_interface import DeviceInterface

logger = logging.getLogger(__name__)

MAGNET_MOTOR_ID = 0

PELLET_X_MOTOR_ID = 0
PELLET_Y_MOTOR_ID = 1
PELLET_Z_MOTOR_ID = 2

PELLET_COVER_SERVO_ID = 0
PELLET_LOAD_SERVO_ID = 1


@dataclass
class ServoConfig:
    min_pos: float = 0
    max_pos: float = 100
    min_pwm: float = 1000
    max_pwm: float = 2000

    max_vel: float = 25.0
    max_acc: float = 100.0

    @classmethod
    def from_dict(cls, data: dict):
        config = ServoConfig()

        if "min_pos" in data:
            config.min_pos = data["min_pos"]
        if "max_pos" in data:
            config.max_pos = data["max_pos"]
        if "min_pwm" in data:
            config.min_pwm = data["min_pwm"]
        if "max_pwm" in data:
            config.max_pwm = data["max_pwm"]
        if "max_vel" in data:
            config.max_vel = data["max_vel"]
        if "max_acc" in data:
            config.max_acc = data["max_acc"]

        return config


@dataclass
class StepperConfig:
    min_step_inverse: int = 64
    steps_per_revolution: float = 48.0

    max_vel: float = 25.0
    max_acc: float = 100.0

    @classmethod
    def from_dict(cls, data: dict):
        config = StepperConfig()

        if "min_step_inverse" in data:
            config.min_step_inverse = data["min_step_inverse"]
        if "steps_per_revolution" in data:
            config.steps_per_revolution = data["steps_per_revolution"]
        if "max_vel" in data:
            config.max_vel = data["max_vel"]
        if "max_acc" in data:
            config.max_acc = data["max_acc"]

        return config


class WhiskerInterface(DeviceInterface):
    """
    Somewhat temporary attempt to confirm the Alogus hardware to the existing device hardware interface.  Will likely
    change substantially.

    WhiskerInterface implements the details of
        * communication (read and write) with Alogus hardware interface (pyjerrcan)

    Applications and scripts would generally not interact with this class directly, but with the more generalized
    behavior in the WhiskerDevice class.
    """

    def __init__(self, magnet_config: typing.Optional[ServoConfig] = None,
                 barrier_config: typing.Optional[ServoConfig] = None,
                 load_arm_config: typing.Optional[ServoConfig] = None, x_config: typing.Optional[StepperConfig] = None,
                 y_config: typing.Optional[StepperConfig] = None, z_config: typing.Optional[StepperConfig] = None):
        super().__init__()

        try:
            self._jc = JerryCAN()
        except:
            self._jc = None

        self._is_open = False

        self._pellet_dst: typing.Optional[int] = None
        self._magnet_dst: typing.Optional[int] = None

        self._magnet_config = magnet_config
        if self._magnet_config is None:
            self._magnet_config = ServoConfig()

        self._load_arm_config = load_arm_config
        if self._load_arm_config is None:
            self._load_arm_config = ServoConfig()

        self._barrier_config = barrier_config
        if self._barrier_config is None:
            self._barrier_config = ServoConfig()

        self._x_config = x_config
        if self._x_config is None:
            self._x_config = StepperConfig()

        self._y_config = y_config
        if self._y_config is None:
            self._y_config = StepperConfig()

        self._z_config = z_config
        if self._z_config is None:
            self._z_config = StepperConfig()

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> bool:
        if self._jc is None:
            return False

        self._is_open = self._jc.Open() == 0

        return self._is_open

    def close(self):
        if self._is_open:
            self._jc.Close()

    def can_read(self) -> bool:
        return self._is_open

    def read(self, max_count: int = 1) -> typing.Any:
        messages = []
        if self._is_open:
            while len(messages) < max_count:
                message = self._jc.ReceiveMessage()
                if message is None:
                    break
                messages.append(message)
                time.sleep(0.0001)

        return messages

    def write(self, value: typing.Any) -> int:
        msg, destination = value
        if self._is_open:
            if self._jc.SendMessage(msg, destination) == 0:
                return 1

        return 0

    def write_str(self, value: str) -> int:
        raise NotImplementedError()

    def configure_pellet(self, dst_id: int):
        self._pellet_dst = dst_id

        if self._is_open and self._pellet_dst is not None:
            self._write_servo_config(self._pellet_dst, PELLET_LOAD_SERVO_ID, self._load_arm_config)
            self._write_servo_config(self._pellet_dst, PELLET_COVER_SERVO_ID, self._barrier_config)
            self._write_stepper_config(self._pellet_dst, PELLET_X_MOTOR_ID, self._x_config)
            self._write_stepper_config(self._pellet_dst, PELLET_Y_MOTOR_ID, self._y_config)
            self._write_stepper_config(self._pellet_dst, PELLET_Z_MOTOR_ID, self._z_config)

    def configure_magnet(self, dst_id: int):
        self._magnet_dst = dst_id

        if self._is_open and self._magnet_dst is not None:
            self._write_servo_config(self._magnet_dst, MAGNET_MOTOR_ID, self._magnet_config)

    def tare_load_cell(self):
        if self._is_open and self._magnet_dst is not None:
            self._jc.LoadCellTare(self._magnet_dst, 0)

    def set_magnet_intensity(self, dst_id: int, intensity: float):
        if self._is_open and self._magnet_dst is not None:
            logger.info(f"set magnet intensity {intensity}")
            self._jc.ServoMove(dst_id, MAGNET_MOTOR_ID, intensity, self._magnet_config.max_vel,
                               self._magnet_config.max_acc, AbsOrRel.ABSOLUTE)

    def set_x(self, value: float):
        if self._is_open and self._pellet_dst is not None:
            logger.info(f"set pellet absolute x {value}")
            self._jc.StepperMove(self._pellet_dst, PELLET_X_MOTOR_ID, value, self._x_config.max_vel,
                                 self._x_config.max_acc, AbsOrRel.ABSOLUTE)

    def set_y(self, value: float):
        if self._is_open and self._pellet_dst is not None:
            logger.info(f"set pellet absolute y {value}")
            self._jc.StepperMove(self._pellet_dst, PELLET_Y_MOTOR_ID, value, self._y_config.max_vel,
                                 self._y_config.max_acc, AbsOrRel.ABSOLUTE)

    def set_z(self, value: float):
        if self._is_open and self._pellet_dst is not None:
            logger.info(f"set pellet absolute z {value}")
            self._jc.StepperMove(self._pellet_dst, PELLET_Z_MOTOR_ID, value, self._z_config.max_vel,
                                 self._z_config.max_acc, AbsOrRel.ABSOLUTE)

    def set_load(self, value: float):
        if self._is_open and self._pellet_dst is not None:
            logger.info(f"set load arm {value}")
            self._jc.ServoMove(self._pellet_dst, PELLET_LOAD_SERVO_ID, value, self._load_arm_config.max_vel,
                               self._load_arm_config.max_acc, AbsOrRel.ABSOLUTE)

    def set_barrier(self, value):
        if self._is_open and self._pellet_dst is not None:
            logger.info(f"set barrier arm {value}")
            self._jc.ServoMove(self._pellet_dst, PELLET_COVER_SERVO_ID, value, self._barrier_config.max_vel,
                               self._barrier_config.max_acc, AbsOrRel.ABSOLUTE)

    def release_pellet(self):
        if self._is_open and self._pellet_dst is not None:
            logger.info(f"release pellet {self._barrier_config.min_pos}")
            self._jc.ServoMove(self._pellet_dst, PELLET_COVER_SERVO_ID, self._barrier_config.min_pos,
                               self._barrier_config.max_vel, self._barrier_config.max_acc,
                               AbsOrRel.ABSOLUTE)

            self.tone_write(self._pellet_dst, 6000)

    def cover_pellet(self):
        if self._is_open and self._pellet_dst is not None:
            logger.info(f"cover pellet {self._barrier_config.max_pos}")
            self._jc.ServoMove(self._pellet_dst, PELLET_COVER_SERVO_ID, self._barrier_config.max_pos,
                               self._barrier_config.max_vel, self._barrier_config.max_acc,
                               AbsOrRel.ABSOLUTE)

    def _write_stepper_config(self, dst_id: int, motor_id: int, config: StepperConfig) -> bool:
        if self._is_open:
            if self._jc.StepperCfgWrite(dst_id, motor_id, config.min_step_inverse, config.steps_per_revolution) == 0:
                logger.debug(
                    f"stepper {dst_id} {motor_id} config write: {config.min_step_inverse} {config.steps_per_revolution}")
                return True
            else:
                logger.error(f"stepper {dst_id} {motor_id} config write failed")

        return False

    def _write_servo_config(self, dst_id: int, motor_id: int, servo_config: ServoConfig) -> bool:
        if self._is_open:
            if self._jc.ServoCfgWrite(dst_id, motor_id, servo_config.min_pos, servo_config.max_pos,
                                      servo_config.min_pwm, servo_config.max_pwm) == 0:
                logger.debug(
                    f"servo {dst_id} {motor_id} config write: {servo_config.min_pos} {servo_config.max_pos} {servo_config.min_pwm} {servo_config.max_pwm}")
                return True
            else:
                logger.error(f"servo {dst_id} {motor_id} config write failed")

        return False

    def request_servo_read(self, dst: int, motor_id: int) -> bool:
        if self._is_open:
            msg = JerryCANCfgMsg()
            msg.type = JerryCANCfgMsg.Type.SERVO
            msg.servo.motor_id = motor_id
            if self._jc.CfgRead(dst, msg) == 0:
                return True

        return False

    def tone_write(self, frequency, duration: int = 1000):
        self._jc.ToneWrite(self._pellet_dst, 0, frequency, duration)
