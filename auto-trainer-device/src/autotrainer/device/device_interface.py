"""
Interface classes that define the capabilities of the mouse gym hardware in a way
that hardware can be swapped or emulated.

There is a set of enumerations that define entities of the hardware:
+ Target - Either the Pellet or Magnet module
+ Motor - Motor that can be controlled
+ DigitalOutputs - Set of available digital outputs
+ AnalogOutputs - Set of available analog outputs

There is a set of data classes that contain state and status of the gym hardware.

There is a main interface class (DeviceInterface) that defines the API for access to the abstracted
hardware.
"""
import math
import typing
from dataclasses import dataclass
from enum import IntEnum

from autotrainer.core.message import Motor


class Target(IntEnum):
    PELLET_DEVICE = 0
    MAGNET_DEVICE = 1


class DigitalOutputs(IntEnum):
    STIMULUS_1 = 1
    STIMULUS_2 = 2
    STIMULUS_3 = 3
    STIMULUS_4 = 4


class AnalogOutputs(IntEnum):
    STATUS_OUT = 0


@dataclass
class Source:
    """
    Base class of any data set received by the device
    """
    target: Target = None

    def __init(self, target: Target = None):
        self.target = target


@dataclass
class Heartbeat(Source):
    unused: bool = False


@dataclass
class MagnetDigitalInputs(Source):
    continuity_0: bool = False
    continuity_1: bool = False


@dataclass
class PelletDigitalInputs(Source):
    stimulus_1: bool = False
    stimulus_2: bool = False
    stimulus_3: bool = False
    stimulus_4: bool = False


@dataclass
class ServoConfig(Source):
    _motor: Motor = Motor.NONE
    _min_position: float = 0  # (deg)
    _max_position: float = 120  # (deg)
    _min_pwm_duration: float = 1000  # (us)
    _max_pwm_duration: float = 2000  # (us)
    _max_velocity: float = 200  # (deg/sec)
    _max_acceleration: float = 100.0  # (deg/sec^2)

    @classmethod
    def from_dict(cls, data: dict):
        config = ServoConfig()

        if "min_pos" in data:
            config.min_position = data["min_pos"]
        if "max_pos" in data:
            config.max_position = data["max_pos"]
        if "min_pwm" in data:
            config.min_pwm_duration_us = data["min_pwm"]
        if "max_pwm" in data:
            config.max_pwm_duration_us = data["max_pwm"]
        if "max_vel" in data:
            config.max_velocity = data["max_vel"]
        if "max_acc" in data:
            config.max_acceleration = data["max_acc"]

        return config

    @property
    def motor(self) -> Motor:
        return self._motor

    @motor.setter
    def motor(self, value: Motor):
        self._motor = value

    @property
    def maximum_velocity(self) -> float:
        return self._max_velocity

    @maximum_velocity.setter
    def maximum_velocity(self, value: float):
        self._max_velocity = value

    @property
    def maximum_acceleration(self) -> float:
        return self._max_acceleration

    @maximum_acceleration.setter
    def maximum_acceleration(self, value: float):
        self._max_acceleration = value

    @property
    def minimum_position(self) -> float:
        return self._min_position

    @minimum_position.setter
    def minimum_position(self, value: float):
        self._min_position = value

    @property
    def maximum_position(self) -> float:
        return self._max_position

    @maximum_position.setter
    def maximum_position(self, value: float):
        self._max_position = value

    @property
    def minimum_pwm_duration(self) -> float:
        return self._min_pwm_duration

    @minimum_pwm_duration.setter
    def minimum_pwm_duration(self, value: float):
        self._min_pwm_duration = value

    @property
    def maximum_pwm_duration(self) -> float:
        return self._max_pwm_duration

    @maximum_pwm_duration.setter
    def maximum_pwm_duration(self, value: float):
        self._max_pwm_duration = value


@dataclass
class ServoStatus(Source):
    motor: Motor = Motor.NONE
    position: float = 0

    def __init__(self, target: Target, motor: Motor, position: float):
        super().__init__(target)
        self.motor = motor
        self.position = position

    @property
    def location(self) -> float:
        """Current servo position in degrees."""
        return self.position

    @property
    def status(self) -> int:
        """Current servo status value."""
        return 0


@dataclass
class StepperConfig(Source):
    _motor: Motor = Motor.NONE
    _micro_steps: int = 64
    _steps_per_revolution: float = 48.0
    _max_velocity: float = 25.0
    _max_acceleration: float = 100.0
    _flip_limit_orientation: bool = False

    @classmethod
    def from_dict(cls, data: dict):
        config = StepperConfig()

        if "microsteps" in data:
            config.min_step_inverted = data["microsteps"]
        if "steps_per_revolution" in data:
            config.steps_per_revolution = data["steps_per_revolution"]
        if "max_vel" in data:
            config.max_velocity = data["max_vel"]
        if "max_acc" in data:
            config.max_acceleration = data["max_acc"]
        if "flip_limit_orientation" in data:
            config.flip_limit_orientation = data["flip_limit_orientation"] == 1

        return config

    @property
    def motor(self) -> Motor:
        return self._motor

    @motor.setter
    def motor(self, value: Motor):
        self._motor = value

    @property
    def maximum_velocity(self) -> float:
        return self._max_velocity

    @maximum_velocity.setter
    def maximum_velocity(self, value: float):
        self._max_velocity = value

    @property
    def maximum_acceleration(self) -> float:
        return self._max_acceleration

    @maximum_acceleration.setter
    def maximum_acceleration(self, value: float):
        self._max_acceleration = value

    @property
    def microsteps(self) -> int:
        return self._micro_steps

    @microsteps.setter
    def microsteps(self, value: int):
        self._micro_steps = value

    @property
    def steps_per_revolution(self) -> float:
        return self._steps_per_revolution

    @steps_per_revolution.setter
    def steps_per_revolution(self, value: float):
        self._steps_per_revolution = value

    @property
    def flip_limit_orientation(self) -> int:
        return self._flip_limit_orientation

    @flip_limit_orientation.setter
    def flip_limit_orientation(self, value: int):
        self._flip_limit_orientation = value


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

    @property
    def location(self) -> float:
        """Current motor position in turns."""
        return self.position

    @property
    def status(self) -> int:
        return 0

    @property
    def limit_hi(self) -> bool:
        return self.limit_switch


@dataclass
class Tone(Source):
    time_remaining_ms: int = 0
    frequency_hz: int = 0


@dataclass
class AnalogOutput(Source):
    status_out_mv: int = 0


@dataclass
class LoadCellReading(Source):
    load_mv: float = 0


@dataclass
class PressureReading(Source):
    pressure_mv: float = 0


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
