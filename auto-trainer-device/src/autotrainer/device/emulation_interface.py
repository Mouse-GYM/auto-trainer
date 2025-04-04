import logging
import time
import typing
from random import uniform, random

from .device_interface import (DeviceInterface, ServoConfig, StepperConfig,
                               StepperStatus, ServoStatus, Target, DigitalOutputs,
                               Motor, AnalogOutputs, SensorStatus, MagnetDigitalInputs,
                               AudioData, PressureReading, LoadCellReading, Version
                               )

logger = logging.getLogger(__name__)

# Slower than the real hardware to be more forgiving in emulation.
_STATUS_MESSAGE_INTERVAL = 2.0
_AUDIO_MESSAGE_INTERVAL = 0.5
_DATA_MESSAGE_INTERVAL = 0.1


class EmulationInterface(DeviceInterface):
    def __init__(self):

        self._is_open = True

        self._last_status_message = 0.0
        self._last_audio_message = 0.0
        self._last_data_message = 0.0

        self._version_requested = False

        self._pellet_x = 0.0
        self._pellet_y = 0.0
        self._pellet_z = 0.0

        self._load_pos = 0.0
        self._cover_pos = 0.0

        self._magnet_pos = 0.0

        self._servo_configs = {
            Motor.PELLET_LOAD_SERVO: ServoConfig(Target.PELLET_DEVICE, Motor.PELLET_LOAD_SERVO),
            Motor.PELLET_COVER_SERVO: ServoConfig(Target.PELLET_DEVICE, Motor.PELLET_COVER_SERVO),
            Motor.MAGNET_SERVO: ServoConfig(Target.MAGNET_DEVICE, Motor.MAGNET_SERVO)}

    def open(self) -> bool:
        return self._is_open

    def close(self):
        pass

    def can_read(self) -> bool:
        return self._is_open

    def read(self, max_count: int = 1) -> typing.Any:
        messages = []

        if self._version_requested:
            messages.append(Version(Target.PELLET_DEVICE, "Pellet Emulator v0.1.0"))
            messages.append(Version(Target.MAGNET_DEVICE, "Magnet Emulator v0.1.0"))
            self._version_requested = False

        now = time.perf_counter()

        # Just to do one type, even if all should be updated.  Do not want this to be taking up much time.
        if now - self._last_status_message > _STATUS_MESSAGE_INTERVAL:
            self._last_status_message = now
            messages.append(
                StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR, self._pellet_x, self._pellet_x == 0))
            messages.append(
                StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_Y_MOTOR, self._pellet_y, self._pellet_y == 0))
            messages.append(
                StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_Z_MOTOR, self._pellet_z, self._pellet_z == 0))

            messages.append(ServoStatus(Target.PELLET_DEVICE, Motor.PELLET_COVER_SERVO, self._cover_pos))
            messages.append(ServoStatus(Target.PELLET_DEVICE, Motor.PELLET_LOAD_SERVO, self._load_pos))

            messages.append(ServoStatus(Target.MAGNET_DEVICE, Motor.MAGNET_SERVO, self._magnet_pos))

            messages.append(SensorStatus(temperature_c=28.0 + uniform(-2, 2), humidity_percent=50.0 + uniform(-2, 2)))
            messages.append(MagnetDigitalInputs(continuity_0=random() < 0.1, continuity_1=False))
        elif now - self._last_audio_message > _AUDIO_MESSAGE_INTERVAL:
            self._last_audio_message = now
            audio = AudioData(target=Target.MAGNET_DEVICE, packet_id=1, when=time.time(), index=time.perf_counter_ns())
            spectrum = []
            for _ in range(32):
                spectrum.append(uniform(0, 20))
            audio.magnitudes = spectrum
            messages.append(audio)
        elif now - self._last_data_message > _DATA_MESSAGE_INTERVAL:
            self._last_data_message = now
            messages.append(PressureReading(pressure=512 + uniform(-10, 10), ))
            messages.append(LoadCellReading(load=uniform(0, 20)))

        return messages

    def write(self, value: typing.Any) -> int:
        if self._is_open:
            return 1

        return 0

    @property
    def cover_config(self):
        return self._servo_configs[Motor.PELLET_COVER_SERVO]

    def request_version(self):
        if self._is_open:
            self._version_requested = True
            logger.info(f"request version")
        return self._is_open

    def tare_pressure_sensor(self):
        if self._is_open:
            logger.info(f"tare pressure sensor")
        return self._is_open

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

    def set_magnet(self, position: float) -> bool:
        if self._is_open:
            logger.info(f"set magnet position {position}")
            self._magnet_pos = position
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

    def set_cover(self, position) -> bool:
        if self._is_open:
            logger.info(f"set barrier arm {position}")
            self._cover_pos = position + 0.00000001
        return self._is_open

    def release_pellet(self) -> bool:
        if self._is_open:
            logger.info("release pellet")
        return self.set_cover(self._servo_configs[Motor.PELLET_COVER_SERVO].minimum_position)

    def cover_pellet(self) -> bool:
        if self._is_open:
            logger.info("cover pellet")
        return self.set_cover(self._servo_configs[Motor.PELLET_COVER_SERVO].maximum_position)

    def emit_tone(self, frequency, duration) -> bool:
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

    def stepper_home(self, motor):
        self._pellet_x = 0.0
        self._pellet_y = 0.0
        self._pellet_z = 0.0
