import pytest

pytestmark = pytest.mark.canbus

try:
    from pyjerrycan import StepperStatus
except (ModuleNotFoundError, TypeError, AttributeError):
    pass

from autotrainer.core.message import SystemStatusMessageKind, SystemCommandKind
from autotrainer.device import (CanDevice, DeviceApi, Target, LoadCellReading,
                                PressureReading, SensorStatus, MagnetDigitalInputs,
                                Motor, StepperStatus, ServoStatus, ServoConfig,
                                StepperConfig
                                )

_expected = None


@pytest.fixture(scope="module")
def device():
    try:
        device = CanDevice(api=DeviceApi(message_callback=data_callback), force_emulation=True)
    except (ModuleNotFoundError, TypeError, AttributeError):
        assert False

    device._interface.magnet_address = 0x40
    device._interface.pellet_address = 0x01

    yield device


@pytest.mark.parametrize("kind, tag, data", [
    (SystemCommandKind.REQUEST_VERSION, 101, None),
    (SystemCommandKind.UPDATE_SCALE_TARE, 102, None),
    (SystemCommandKind.SET_X, 103, 10),
    (SystemCommandKind.SET_Y, 104, 15),
    (SystemCommandKind.SET_Z, 105, 20),
    (SystemCommandKind.MOVE_X, 106, 10),
    (SystemCommandKind.MOVE_Y, 106, 15),
    (SystemCommandKind.MOVE_Z, 108, 20),
    (SystemCommandKind.MOVE_MAGNET_SERVO, 109, 25),
    (SystemCommandKind.MOVE_GATE_SERVO, 110, 30),
    (SystemCommandKind.MOVE_LOAD_SERVO, 111, 35),
    (SystemCommandKind.MOVE_COVER_SERVO, 112, 40),
    (SystemCommandKind.SEND_HOME, 113, None),
    (SystemCommandKind.LOAD_PELLET, 114, None),
    (SystemCommandKind.SEND_PELLET, 115, None),
    (SystemCommandKind.RELEASE_PELLET, 116, None),
    (SystemCommandKind.COVER_PELLET, 117, None),
    (SystemCommandKind.PLAY_TONE, 118, None),
    (SystemCommandKind.DELAY, 119, None),
    (SystemCommandKind.READ_MOTOR_CONFIGURATION, 120, None),
    (SystemCommandKind.WRITE_MOTOR_CONFIGURATION, 121, (Motor.PELLET_X_MOTOR, StepperConfig())),
    (SystemCommandKind.SEND_FIXED_XYZ, 122, None)
])
def test_notify_command(device, kind, tag, data):
    device.notify_message(kind, data, tag)


@pytest.mark.parametrize("data, kind", [
    (LoadCellReading(target=Target.MAGNET_DEVICE, load=13), None),
    (PressureReading(Target.MAGNET_DEVICE, pressure=14), None),
    (SensorStatus(Target.PELLET_DEVICE, temperature_c=27.3, humidity_percent=64.2), None),
    (MagnetDigitalInputs(Target.MAGNET_DEVICE, continuity_0=False, continuity_1=True), None),
    (StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR, 10, 2.0, False),
     SystemStatusMessageKind.PELLET_X),
    (ServoStatus(Target.PELLET_DEVICE, Motor.PELLET_LOAD_SERVO, 40),
     SystemStatusMessageKind.PELLET_LOAD),
    (ServoConfig(Target.MAGNET_DEVICE, Motor.PELLET_X_MOTOR, 0, 0, 0, 0, 0, 0),
     SystemStatusMessageKind.MOTOR_CONFIGURATION),
    (StepperConfig(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR, 0, 0, 0, 0, False),
     SystemStatusMessageKind.MOTOR_CONFIGURATION)
])
def test_notify_data(device, data, kind):
    global _expected

    if kind:
        _expected = kind

    device.notify_data([data])


def data_callback(kind: int, response: object):
    assert kind == _expected
