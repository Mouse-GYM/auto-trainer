# must be firsts to prevent partial import name error because of import loop cycle(s):
from typing import Protocol

# keep top-level:
class IsCancelledT(Protocol):
    def __call__(self) -> bool:
        """True if operation canceled"""


def default_not_cancelled() -> bool:
    """For default is_canceled"""
    return False


# before below:

from .motor_steps import MotorSteps
from .compound_movement_file import CompoundMovements
from .motor_configuration_file import MotorConfigurationFile

from .device import Device
from .device_api import DeviceApi
from .can_interface import (CanInterface, motor_to_str, target_to_str, is_stepper, is_servo,
                            target_of_motor)
from .device_connection import DeviceConnection
from .device_connection_protocol import DeviceConnectionProtocol
from .device_interface import (DeviceInterface, Target, Motor, ServoConfig, StepperConfig,
                               Heartbeat, DigitalOutputs, MagnetDigitalInputs, PelletDigitalInputs,
                               Tone, AnalogOutput, AnalogOutputs, LoadCellReading, PressureReading,
                               ColorLed, AudioData, DoorData, StepperStatus, ServoStatus,
                               SensorStatus, Status)
from .emulation_interface import EmulationInterface
from .can_device import CanDevice, HAVE_CAN_DEVICE
