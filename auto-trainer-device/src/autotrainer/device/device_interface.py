import math
import typing
from dataclasses import dataclass
from enum import Enum


@dataclass
class Target(Enum):
    PELLET_DEVICE = 0
    MAGNET_DEVICE = 1


@dataclass
class Motor(Enum):
    NONE = 0
    MAGNET_SERVO = 1
    PELLET_X_MOTOR = 2
    PELLET_Y_MOTOR = 3
    PELLET_Z_MOTOR = 4
    PELLET_COVER_SERVO = 5
    PELLET_LOAD_SERVO = 6


@dataclass
class DigitalOutputs(Enum):
    STIMULUS_1 = 1
    STIMULUS_2 = 2
    STIMULUS_3 = 3
    STIMULUS_4 = 4


@dataclass
class AnalogOutputs(Enum):
    STATUS_OUT = 0


@dataclass
class Source:
    target: Target = None

    def __init(self, target: Target = None):
        self.target = target


@dataclass
class Heartbeat(Source):
    unused: bool = False


@dataclass
class MagnetDigitalInputs(Source):
    continuity_0 = False
    continuity_1 = False


@dataclass
class PelletDigitalInputs(Source):
    stimulus_1 = False
    stimulus_2 = False
    stimulus_3 = False
    stimulus_4 = False


@dataclass
class ServoConfig(Source):
    motor: Motor = Motor.NONE
    error: bool = False
    min_position: float = 0
    max_position: float = 100
    min_pwm_duration_us: float = 1000
    max_pwm_duration_us: float = 2000

    max_vel: float = 25.0
    max_acc: float = 100.0

    @classmethod
    def from_dict(cls, data: dict):
        config = ServoConfig()

        if "min_pos" in data:
            config.min_position = data["min_pos"]
        if "max_pos" in data:
            config.max_position = data["max_pos"]
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
class ServoStatus(Source):
    motor: Motor = Motor.NONE
    position: float = 0

    def __init__(self, target: Target, motor: Motor, position: float):
        super().__init__(target)
        self.motor = motor
        self.position = position


@dataclass
class StepperConfig(Source):
    motor: Motor = Motor.NONE
    error: bool = False
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


@dataclass
class StepperStatus(Source):
    motor: Motor = Motor.NONE
    position: float = 0
    limit_switch: bool = False

    def __init__(self, target: Target, motor: Motor, position: float, limit_switch: bool):
        super().__init__(target)

        self.motor = motor
        self.position = position
        self.limit_switch = limit_switch


@dataclass
class Tone(Source):
    time_remaining_ms: int = 0
    frequency_hz: int = 0


@dataclass
class AnalogOutput(Source):
    status_out_mv: int = 0


@dataclass
class LoadCellReading(Source):
    load: float = 0


@dataclass
class PressureReading(Source):
    pressure: float = 0


@dataclass
class ColorLed(Source):
    red: int = 0
    green: int = 0
    blue: int = 0


@dataclass
class AudioData(Source):
    packet_id: int = 0
    magnitudes = []


@dataclass
class DoorData(Source):
    open_state = [False, False, False]


@dataclass
class Status(Source):
    unused: bool = True


@dataclass
class SensorStatus(Source):
    temperature_c: float = 0
    humidity_percent: float = 0


class DeviceInterface:
    """ Defines the required methods for a class that provides low-level communication with a device, such as serial"""

    def open(self) -> bool:
        """ Opens the interface

        This method should not raise an exception and return False instead.  Exception details may be logged.

        :return: True if successfully opened
        """
        return False

    def close(self):
        pass

    @property
    def is_open(self) -> bool:
        return False

    def can_read(self) -> bool:
        pass

    def read(self, max_count: int = math.inf) -> typing.Any:
        """ Reads the available number of values from the interface up to max_count

        :param max_count: maximum number of values to read
        :returns typing.Any: the data
        :rtype: typing.Any
        """
        pass

    def write(self, value: typing.Any) -> int:
        """ Writes the content value(s) to the interface

        :param value: The content to be written
        :return: the number of values written"""
        pass

    def write_str(self, value: str) -> int:
        """ Writes the string to the interface

        :param value: The string to be written
        :return: the number of bytes written"""
        pass
