import logging
import time

from .device_interface import *
from .can_interface import motor_to_str

logger = logging.getLogger(__name__)


class EmulationInterface(DeviceInterface):
    def __init__(self):

        self._is_open = False

        self._last_message = 0.0

        self._positions = {
            Motor.PELLET_LOAD_SERVO: 0.0,
            Motor.PELLET_X_MOTOR: 0.0,
            Motor.PELLET_Y_MOTOR: 0.0,
            Motor.PELLET_Z_MOTOR: 0.0,
            Motor.MAGNET_SERVO: 0.0,
            Motor.PELLET_COVER_SERVO: 0.0,
        }

        self._configs = {
            Motor.PELLET_LOAD_SERVO: ServoConfig(Target.PELLET_DEVICE, Motor.PELLET_LOAD_SERVO),
            Motor.PELLET_COVER_SERVO: ServoConfig(Target.PELLET_DEVICE, Motor.PELLET_COVER_SERVO),
            Motor.MAGNET_SERVO: ServoConfig(Target.MAGNET_DEVICE, Motor.MAGNET_SERVO),
            Motor.PELLET_X_MOTOR: StepperConfig(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR),
            Motor.PELLET_Y_MOTOR: StepperConfig(Target.PELLET_DEVICE, Motor.PELLET_Y_MOTOR),
            Motor.PELLET_Z_MOTOR: StepperConfig(Target.PELLET_DEVICE, Motor.PELLET_Z_MOTOR),
        }

    def open(self) -> bool:
        self._is_open = True
        return self._is_open

    def close(self):
        self._is_open = False

    def can_read(self) -> bool:
        return self._is_open

    def read(self, max_count: int = 1) -> typing.Any:
        messages = []
        now = time.perf_counter()
        if now - self._last_message > 1:
            self._last_message = now
            messages.append(
                StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR,
                              self._positions[Motor.PELLET_X_MOTOR],
                              self._positions[Motor.PELLET_X_MOTOR] == 0))

            messages.append(
                StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_Y_MOTOR,
                              self._positions[Motor.PELLET_Y_MOTOR],
                              self._positions[Motor.PELLET_Y_MOTOR] == 0))

            messages.append(
                StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_Z_MOTOR,
                              self._positions[Motor.PELLET_Z_MOTOR],
                              self._positions[Motor.PELLET_Z_MOTOR] == 0))

            messages.append(
                ServoStatus(Target.PELLET_DEVICE, Motor.PELLET_COVER_SERVO, self._positions[
                    Motor.PELLET_COVER_SERVO]))

            messages.append(
                ServoStatus(Target.PELLET_DEVICE, Motor.PELLET_LOAD_SERVO,
                            self._positions[Motor.PELLET_LOAD_SERVO]))

            messages.append(ServoStatus(Target.MAGNET_DEVICE, Motor.MAGNET_SERVO,
                                        self._positions[Motor.MAGNET_SERVO]))

            messages.append(Version(Target.PELLET_DEVICE, "v1.0.0"))

            messages.append(self.cover_config)
            messages.append(self.load_config)
            messages.append(self.magnet_config)
            messages.append(self.x_config)
            messages.append(self.y_config)
            messages.append(self.z_config)
            messages.append(MagnetDigitalInputs(Target.MAGNET_DEVICE, True, False))
            messages.append(PelletDigitalInputs(Target.PELLET_DEVICE, True, False, True, False))

            messages.append(PressureReading())
            messages.append(DoorData())
            messages.append(SensorStatus())

            # keep this one last; see can_device
            messages.append(LoadCellReading(Target.MAGNET_DEVICE, 0.25))

        return messages

    def write(self, value: typing.Any) -> int:
        if self._is_open:
            return 1

        return 0

    @property
    def cover_config(self):
        return self._configs[Motor.PELLET_COVER_SERVO]

    @property
    def load_config(self):
        return self._configs[Motor.PELLET_LOAD_SERVO]

    @property
    def magnet_config(self):
        return self._configs[Motor.MAGNET_SERVO]

    @property
    def x_config(self):
        return self._configs[Motor.PELLET_X_MOTOR]

    @property
    def y_config(self):
        return self._configs[Motor.PELLET_Y_MOTOR]

    @property
    def z_config(self):
        return self._configs[Motor.PELLET_Z_MOTOR]

    def set_motor_configuration(self, motor: Motor, config, _write_to_remote: bool = True) -> bool:
        if self._is_open:
            logger.info(f"Set motor configuration {int(motor.value)}")
            self._configs[motor] = config
        return self._is_open

    def tare_load_cell(self) -> bool:
        if self._is_open:
            logger.info(f"tare load cell")
        return self._is_open

    def tare_pressure_sensor(self) -> bool:
        if self._is_open:
            logger.info(f"tare pressure sensor")
        return self._is_open

    def set_magnet(self, position: float) -> bool:
        if self._is_open:
            logger.info(f"set magnet position {position}")
            self._positions[Motor.MAGNET_SERVO] = position + 0.01
        return self._is_open

    def set_x(self, position: float) -> bool:
        if self._is_open:
            logger.info(f"set pellet absolute x {position}")
            self._positions[Motor.PELLET_X_MOTOR] = position + 0.01
        return self._is_open

    def set_y(self, position: float) -> bool:
        if self._is_open:
            logger.info(f"set pellet absolute y {position}")
            self._positions[Motor.PELLET_Y_MOTOR] = position + 0.01
        return self._is_open

    def set_z(self, position: float) -> bool:
        if self._is_open:
            logger.info(f"set pellet absolute z {position}")
            self._positions[Motor.PELLET_Z_MOTOR] = position + 0.01
        return self._is_open

    def set_load(self, position: float) -> bool:
        if self._is_open:
            logger.info(f"set load arm {position}")
            self._positions[Motor.PELLET_LOAD_SERVO] = position + 0.01
        return self._is_open

    def set_cover(self, position) -> bool:
        if self._is_open:
            logger.info(f"set barrier arm {position}")
            self._positions[Motor.PELLET_COVER_SERVO] = position + 0.01
        return self._is_open

    def release_pellet(self) -> bool:
        if self._is_open:
            logger.info("release pellet")
        return self.set_cover(self._configs[Motor.PELLET_COVER_SERVO].minimum_position)

    def cover_pellet(self) -> bool:
        if self._is_open:
            logger.info("cover pellet")
        return self.set_cover(self._configs[Motor.PELLET_COVER_SERVO].maximum_position)

    def stepper_home(self, motor: Motor):
        self._positions[motor] = 0.0

    def request_motor_config(self, motor: Motor) -> bool:
        if self._is_open:
            logger.info(f"request motor config {motor_to_str(motor)}")
        return self._is_open

    def send_heartbeat(self) -> bool:
        return self._is_open

    def set_digital_output(self, gpio: DigitalOutputs, state: bool) -> bool:
        if self._is_open:
            logger.info(f"Set digital output {int(gpio.value)} -> {state}")
        return self._is_open

    def emit_tone(self, frequency, duration) -> bool:
        if self._is_open:
            logger.info(f"play tone f={frequency} d={duration}")
        return self._is_open

    def set_analog_output(self, channel: AnalogOutputs, millivolts: int) -> bool:
        if self._is_open:
            logger.info(f"Set analog output {int(channel.value)} -> {millivolts}")
        return self._is_open

    def set_color_led(self, red_percent: int, green_percent: int, blue_percent: int) -> bool:
        if self._is_open:
            logger.info(f"Set color LED ({red_percent}, {green_percent}, {blue_percent})")
        return self._is_open

    def request_version(self) -> bool:
        return self._is_open
