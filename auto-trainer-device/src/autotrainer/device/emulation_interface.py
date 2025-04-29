import logging
import time
import typing
from copy import deepcopy
from random import uniform, random

from .device_interface import (DeviceInterface, ServoConfig, StepperConfig,
                               StepperStatus, ServoStatus, Target, DigitalOutputs,
                               Motor, AnalogOutputs, SensorStatus, MagnetDigitalInputs,
                               AudioData, PressureReading, LoadCellReading, Version,
                               PelletDigitalInputs, DoorData, Acknowledge
                               )
from .can_interface import motor_to_str

logger = logging.getLogger(__name__)

# Slower than the real hardware to be more forgiving in emulation.
_STATUS_MESSAGE_INTERVAL = 2.0
_AUDIO_MESSAGE_INTERVAL = 0.5
_DATA_MESSAGE_INTERVAL = 0.1


class EmulationInterface(DeviceInterface):
    _uuid: int = 1

    @classmethod
    def next_uuid(cls) -> int:
        cls._uuid = cls._uuid + 1 & 0xFF
        if cls._uuid == 0:  # don't allow 0's
            cls._uuid = 1
        return cls._uuid

    @classmethod
    def uuid(cls) -> int:
        return cls._uuid

    def __init__(self):

        self._is_open = False

        self._last_status_message = 0.0
        self._last_audio_message = 0.0
        self._last_data_message = 0.0

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

        self._messages = []

    def _set_pellet_address(self, addr):
        pass

    def _set_magnet_address(self, addr):
        pass

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> bool:
        self._is_open = True
        return self._is_open

    def close(self):
        self._is_open = False

    def can_read(self) -> bool:
        return self._is_open

    def read(self, max_count: int = 1) -> typing.Any:

        messages = deepcopy(self._messages)
        self._messages = []

        now = time.perf_counter()

        # Just to do one type, even if all should be updated.  Do not want this to be taking up much time.
        if now - self._last_status_message > _STATUS_MESSAGE_INTERVAL:
            self._last_status_message = now
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

            messages.append(MagnetDigitalInputs(continuity_0=random() < 0.1, continuity_1=False))
            messages.append(PelletDigitalInputs(Target.PELLET_DEVICE, True, False, True, False))
            messages.append(DoorData())
            messages.append(SensorStatus(temperature_c=28.0 + uniform(-2, 2),
                                         humidity_percent=50.0 + uniform(-2, 2)))

        elif now - self._last_audio_message > _AUDIO_MESSAGE_INTERVAL:
            self._last_audio_message = now
            audio = AudioData(target=Target.MAGNET_DEVICE, packet_id=1, when=time.time(),
                              index=time.perf_counter_ns())
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
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def tare_load_cell(self) -> bool:
        if self._is_open:
            logger.info(f"tare load cell")
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def tare_pressure_sensor(self) -> bool:
        if self._is_open:
            logger.info(f"tare pressure sensor")
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def set_magnet(self, position: float, _save: bool = False) -> bool:
        if self._is_open:
            logger.info(f"set magnet position {position}")
            self._positions[Motor.MAGNET_SERVO] = position + 0.00001
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def set_x(self, position: float, _save: bool = False) -> bool:
        if self._is_open:
            logger.info(f"set pellet absolute x {position}")
            self._positions[Motor.PELLET_X_MOTOR] = position + 0.00001
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def set_y(self, position: float, _save: bool = False) -> bool:
        if self._is_open:
            logger.info(f"set pellet absolute y {position}")
            self._positions[Motor.PELLET_Y_MOTOR] = position + 0.00001
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def set_z(self, position: float, _save: bool = False) -> bool:
        if self._is_open:
            logger.info(f"set pellet absolute z {position}")
            self._positions[Motor.PELLET_Z_MOTOR] = position + 0.00001
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def set_load(self, position: float, _save: bool = False) -> bool:
        if self._is_open:
            logger.info(f"set load arm {position}")
            self._positions[Motor.PELLET_LOAD_SERVO] = position + 0.00001
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def retrieve_pellet(self) -> bool:
        if self._is_open:
            logger.info("retreive pellet")
        return self.set_load(self._configs[Motor.PELLET_LOAD_SERVO].maximum_position)

    def scoop_pellet(self) -> bool:
        if self._is_open:
            logger.info("scoop pellet")
        return self.set_load(self._configs[Motor.PELLET_LOAD_SERVO].minimum_position)

    def set_cover(self, position, _save: bool = False) -> bool:
        if self._is_open:
            logger.info(f"set barrier arm {position}")
            self._positions[Motor.PELLET_COVER_SERVO] = position + 0.00001
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def release_pellet(self) -> bool:
        if self._is_open:
            logger.info("release pellet")
        return self.set_cover(self._configs[Motor.PELLET_COVER_SERVO].minimum_position)

    def cover_pellet(self) -> bool:
        if self._is_open:
            logger.info("cover pellet")
        return self.set_cover(self._configs[Motor.PELLET_COVER_SERVO].maximum_position)

    def fixed_position(self) -> bool:
        self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def emit_tone(self, frequency, duration) -> bool:
        if self._is_open:
            logger.info(f"play tone f={frequency} d={duration}")
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def request_motor_config(self, motor: Motor) -> bool:
        if self._is_open:
            logger.info(f"request motor config {motor_to_str(motor)}")
            if motor is Motor.PELLET_COVER_SERVO:
                self._messages.append(self._configs[Motor.PELLET_COVER_SERVO])
            elif motor is Motor.PELLET_LOAD_SERVO:
                self._messages.append(self._configs[Motor.PELLET_LOAD_SERVO])
            elif motor is Motor.MAGNET_SERVO:
                self._messages.append(self._configs[Motor.MAGNET_SERVO])
            elif motor is Motor.PELLET_X_MOTOR:
                self._messages.append(self._configs[Motor.PELLET_X_MOTOR])
            elif motor is Motor.PELLET_Y_MOTOR:
                self._messages.append(self._configs[Motor.PELLET_Y_MOTOR])
            elif motor is Motor.PELLET_Z_MOTOR:
                self._messages.append(self._configs[Motor.PELLET_Z_MOTOR])

            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def send_heartbeat(self) -> bool:
        self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def set_digital_output(self, gpio: DigitalOutputs, state: bool) -> bool:
        if self._is_open:
            logger.info(f"Set digital output {int(gpio.value)} -> {state}")
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def set_analog_output(self, channel: AnalogOutputs, millivolts: int) -> bool:
        if self._is_open:
            logger.info(f"Set analog output {int(channel.value)} -> {millivolts}")
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def set_color_led(self, red_percent: int, green_percent: int, blue_percent: int) -> bool:
        if self._is_open:
            logger.info(f"Set color LED ({red_percent}, {green_percent}, {blue_percent})")
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def stepper_home(self, motor: Motor):
        self._positions[motor] = 0.0
        self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))

    def request_version(self):
        if self._is_open:
            self._version_requested = True
            logger.info(f"request version")
            self._messages.append(Version(Target.PELLET_DEVICE, "Pellet Emulator v0.1.0"))
            self._messages.append(Version(Target.MAGNET_DEVICE, "Magnet Emulator v0.1.0"))

            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))
        return self._is_open

    def delay(self, delay):
        if self._is_open:
            time.sleep(float(delay))
            self._messages.append(Acknowledge(uuid=EmulationInterface.next_uuid()))

        return self._is_open
