import logging
import time
import typing

from . import Motor
from .device_interface import (DeviceInterface, ServoConfig, StepperConfig,
                               StepperStatus, ServoStatus, Target, DigitalOutputs,
                               Motor, AnalogOutputs)

logger = logging.getLogger(__name__)


class EmulationInterface(DeviceInterface):
    def __init__(self):

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
            messages.append(
                StepperStatus(Motor.PELLET_X_MOTOR, self._pellet_x, self._pellet_x == 0))
            messages.append(
                StepperStatus(Motor.PELLET_Y_MOTOR, self._pellet_y, self._pellet_y == 0))
            messages.append(
                StepperStatus(Motor.PELLET_Z_MOTOR, self._pellet_z, self._pellet_z == 0))

            messages.append(ServoStatus(Motor.PELLET_COVER_SERVO, 0, self._barrier_pos))
            messages.append(ServoStatus(Motor.PELLET_LOAD_SERVO, 1, self._load_pos))

            messages.append(ServoStatus(Motor.MAGNET_SERVO, 0, self._magnet_pos))
        return messages

    def write(self, value: typing.Any) -> int:
        if self._is_open:
            return 1

        return 0

    def set_motor_configuration(self, motor: Motor, servo_config=typing.Optional[ServoConfig],
                                stepper_config=typing.Optional[StepperConfig]) -> bool:
        if self._is_open:
            logger.info(f"Set motor configuration {int(motor.value)}")
        return self._is_open

    def configure_pellet(self):
        if self._is_open:
            logger.info(f"Configure all pellet motors")
        return self._is_open

    def configure_magnet(self):
        if self._is_open:
            logger.info(f"Configure all magnet motors")
        return self._is_open

    def tare_load_cell(self) -> bool:
        if self._is_open:
            logger.info(f"tare load cell")
        return self._is_open

    def set_magnet(self, dst_id: int, position: float) -> bool:
        if self._is_open:
            logger.info(f"set magnet position {position}")
        return self._is_open

    def set_x(self, position: float) -> bool:
        if self._is_open:
            logger.info(f"set pellet absolute x {position}")
            self._pellet_x = position + 0.00000001
        return self._is_open

    def set_y(self, position: float) -> bool:
        if self._is_open:
            logger.info(f"set pellet absolute y {position}")
            self._pellet_y = position + 0.00000001
        return self._is_open

    def set_z(self, position: float) -> bool:
        if self._is_open:
            logger.info(f"set pellet absolute z {position}")
            self._pellet_z = position + 0.000001
        return self._is_open

    def set_load(self, position: float) -> bool:
        if self._is_open:
            logger.info(f"set load arm {position}")
            self._load_pos = position + 0.000001
        return self._is_open

    def set_barrier(self, position) -> bool:
        if self._is_open:
            logger.info(f"set barrier arm {position}")
        return self._is_open

    def release_pellet(self) -> bool:
        if self._is_open:
            logger.info("release pellet")
        return self.set_barrier(0)

    def cover_pellet(self) -> bool:
        if self._is_open:
            logger.info("cover pellet")
        return self.set_barrier(100)

    def emit_tone(self, dst: int, frequency, duration) -> bool:
        if self._is_open:
            logger.info(f"play tone f{frequency} d{duration}")
        return self._is_open

    def request_servo_config(self, target: Target, motor: Motor) -> bool:
        if self._is_open:
            logger.info(f"request servo config {int(target.value)} {int(motor.value)}")
        return self._is_open

    def request_stepper_config(self, motor: Motor) -> bool:
        if self._is_open:
            logger.info(f"request stepper config {int(Target.PELLET_DEVICE.value)}"
                        f" {int(motor.value)}")
        return self._is_open

    def send_heartbeat(self) -> bool:
        return self._is_open

    def set_digital_output(self, gpio: DigitalOutputs, state: bool) -> bool:
        if self._is_open:
            logger.info(f"Set digital output {int(gpio.value)} -> {state}")
        return self._is_open

    def set_analog_output(self, channel: AnalogOutputs, millivolts: int) -> bool:
        if self._is_open:
            logger.info(f"Set analog output {int(channel.value)} -> {millivolts}")
        return self._is_open

    def set_color_led(self, red_percent: int, green_percent: int, blue_percent: int) -> bool:
        if self._is_open:
            logger.info(f"Set color LED ({red_percent}, {green_percent}, {blue_percent})")
        return self._is_open
