import typing

from .device import Device
from .device_api import DeviceApi
from .can_interface import CanInterface, motor_to_str, target_to_str, is_stepper, is_servo, \
    target_of_motor
from .device_connection import DeviceConnection, DeviceThreadMessageKind
from .device_interface import (DeviceInterface, Target, Motor, ServoConfig, StepperConfig,
                               Heartbeat, DigitalOutputs, MagnetDigitalInputs, PelletDigitalInputs,
                               Tone, AnalogOutput, AnalogOutputs, LoadCellReading, PressureReading,
                               ColorLed, AudioData, DoorData, StepperStatus, ServoStatus,
                               SensorStatus, Status)
from .emulation_interface import EmulationInterface
from .can_device import CanDevice, HAVE_CAN_DEVICE
from .motor_steps import MotorSteps
from .compound_movement_file import CompoundMovementFile
from .motor_configuration_file import MotorConfigurationFile
from .anshutz import HeadFix, PelletDelivery, parse_measurement, parse_measurements

CAN_IDENTIFIER = "CAN"


def get_available_hardware(can_name: str = CAN_IDENTIFIER, allow_can_emulation: bool = False) -> typing.List[str]:
    ports = anshutz.get_available_hardware()

    if HAVE_CAN_DEVICE or allow_can_emulation:
        ports.insert(0, can_name)

    return ports
