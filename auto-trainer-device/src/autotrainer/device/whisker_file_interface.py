import logging
import time
import typing

from .whisker_interface import WhiskerInterface, ServoConfig, StepperConfig

from .pyjerryfile import JerryCANMsg, JerryCANCmdType, JerryStepperStatus

logger = logging.getLogger(__name__)


class WhiskerFileInterface(WhiskerInterface):
    def __init__(self, magnet_config: typing.Optional[ServoConfig] = None,
                 barrier_config: typing.Optional[ServoConfig] = None,
                 load_arm_config: typing.Optional[ServoConfig] = None, x_config: typing.Optional[StepperConfig] = None,
                 y_config: typing.Optional[StepperConfig] = None, z_config: typing.Optional[StepperConfig] = None):
        super().__init__(magnet_config, barrier_config, load_arm_config, x_config, y_config, z_config)

        self._is_open = True

        self._last_message = 0.0

        self._pellet_x = 0.0
        self._pellet_y = 0.0
        self._pellet_z = 0.0

        self._load_pos = 0.0
        self._barrier_pos = 0.0

        self._magnet_pos = 0.0

    def open(self) -> bool:

        return self._is_open

    def close(self):
        pass

    def read(self, max_count: int = 1) -> typing.Any:
        messages = []
        now = time.perf_counter()
        if now - self._last_message > 1:
            self._last_message = now
            messages.append(JerryCANMsg.stepper_message(0, self._pellet_x))
            messages.append(JerryCANMsg.stepper_message(1, self._pellet_y))
            messages.append(JerryCANMsg.stepper_message(2, self._pellet_z))

            messages.append(JerryCANMsg.servo_message(1, 0, self._barrier_pos))
            messages.append(JerryCANMsg.servo_message(1, 1, self._load_pos))

            messages.append(JerryCANMsg.servo_message(4, 0, self._magnet_pos))
        return messages

    def write(self, value: typing.Any) -> int:
        if self._is_open:
            return 1

        return 0

    def tare_load_cell(self):
        if self._is_open:
            logger.info(f"tare load cell")

    def set_magnet_intensity(self, dst_id: int, intensity: float):
        if self._is_open:
            logger.info(f"set magnet intensity {intensity}")

    def set_x(self, value: float):
        if self._is_open:
            logger.info(f"set pellet absolute x {value}")
            self._pellet_x = value + 0.00000001

    def set_y(self, value: float):
        if self._is_open:
            logger.info(f"set pellet absolute y {value}")
            self._pellet_y = value + 0.00000001

    def set_z(self, value: float):
        if self._is_open:
            logger.info(f"set pellet absolute z {value}")
            self._pellet_z = value + 0.000001

    def set_load(self, value: float):
        if self._is_open:
            logger.info(f"set load arm {value}")
            self._load_pos = value + 0.000001

    def release_pellet(self):
        if self._is_open:
            logger.info("release pellet")

    def cover_pellet(self):
        if self._is_open:
            logger.info("cover pellet")

    def _write_stepper_config(self, dst_id: int, motor_id: int, config: StepperConfig) -> bool:
        logger.debug(
            f"stepper {dst_id} {motor_id} config write: {config.min_step_inverse} {config.steps_per_revolution}")
        return True

    def _write_servo_config(self, dst_id: int, motor_id: int, servo_config: ServoConfig) -> bool:
        logger.debug(
            f"servo {dst_id} {motor_id} config write: {servo_config.min_pos} {servo_config.max_pos} {servo_config.min_pwm} {servo_config.max_pwm}")
        return True

    def tone_write(self, dst: int, frequency, duration):
        if self._is_open:
            logger.info(f"play tone f{frequency} d{duration}")
