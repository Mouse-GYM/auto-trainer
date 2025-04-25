import pytest

pytestmark = pytest.mark.canbus

try:
    from pyjerrycan import StepperStatus
except (ModuleNotFoundError, TypeError, AttributeError):
    pass

from autotrainer.core.message import SystemStatusMessageKind, SystemCommandKind
from autotrainer.device import (CanDevice, DeviceApi, CanInterface,
                                Status, Target, LoadCellReading, PressureReading, SensorStatus,
                                MagnetDigitalInputs, Motor, StepperStatus, ServoStatus,
                                ServoConfig, StepperConfig, MotorSteps, HAVE_CAN_DEVICE,
                                EmulationInterface
                                )

_expected = []


def notify_command(kind, tag, data=None, expected=None, repeat=1, expect_ack: bool = True):
    global _expected

    if expected is None:
        expected = []
    device = _construction()
    _expected = expected
    if expect_ack:
        _expected.append((SystemStatusMessageKind.ACKNOWLEDGE, tag))

    for i in range(repeat):
        device.notify_message(kind, data, tag)

    assert len(_expected) == 0


def notify_data(data):
    device = _construction()
    device.notify_data([data])


@pytest.mark.canbus
def data_callback(kind: int, response: object):
    assert len(_expected) != 0

    k, r = _expected.pop(0)

    assert kind == k
    assert response == r


def _construction():
    try:
        device = CanDevice(api=DeviceApi(message_callback=data_callback), force_emulation=True)
    except (ModuleNotFoundError, TypeError, AttributeError):
        assert False

    device._interface._set_magnet_address(0x40)
    device._interface._set_pellet_address(0x01)

    return device


@pytest.mark.canbus
def test_notify_version():
    notify_command(SystemCommandKind.REQUEST_VERSION, 101, expect_ack=False)


@pytest.mark.canbus
def test_notify_tare_load_cell():
    notify_command(SystemCommandKind.UPDATE_SCALE_TARE, 102, expect_ack=False)


@pytest.mark.canbus
def test_notify_set_magnet():
    notify_command(SystemCommandKind.SET_MAGNET_INTENSITY, 103, data=3.0, expect_ack=False)


@pytest.mark.canbus
def test_notify_set_x():
    notify_command(SystemCommandKind.SET_X, 10.4, data=4, expect_ack=False)


@pytest.mark.canbus
def test_notify_set_y():
    notify_command(SystemCommandKind.SET_Y, 10.5, data=5, expect_ack=False)


@pytest.mark.canbus
def test_notify_set_z():
    notify_command(SystemCommandKind.SET_Z, 10.6, data=6, expect_ack=False)


@pytest.mark.canbus
def test_notify_set_home():
    device = _construction()
    device.notify_message(SystemCommandKind.SEND_HOME, None)


@pytest.mark.canbus
def test_notify_load_pellet():
    notify_command(SystemCommandKind.LOAD_PELLET, 107, expect_ack=False)


@pytest.mark.canbus
def test_notify_send_pellet():
    notify_command(SystemCommandKind.SEND_PELLET, 108, expect_ack=False)


@pytest.mark.canbus
def test_notify_release_pellet():
    notify_command(SystemCommandKind.RELEASE_PELLET, 109, expect_ack=False)


@pytest.mark.canbus
def test_notify_cover_pellet():
    notify_command(SystemCommandKind.COVER_PELLET, 110, expect_ack=False)


@pytest.mark.canbus
def test_pellet_status():
    notify_data(Status(Target.MAGNET_DEVICE))


@pytest.mark.canbus
def test_load_cell_reading():
    notify_data(LoadCellReading(Target.MAGNET_DEVICE, 13))


@pytest.mark.canbus
def test_pressure_reading():
    notify_data(PressureReading(Target.MAGNET_DEVICE, 14))


@pytest.mark.canbus
def test_sensor_status():
    notify_data(SensorStatus(Target.PELLET_DEVICE, 27.3, 64.2))


@pytest.mark.canbus
def test_magnet_digital_inputs():
    notify_data(MagnetDigitalInputs(Target.MAGNET_DEVICE, False, True))


@pytest.mark.canbus
def test_stepper_status():
    global _expected

    _expected = [
        (SystemStatusMessageKind.PELLET_X, 10),
    ]
    notify_data(StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR, 10, False))

    _expected = [
        (SystemStatusMessageKind.PELLET_Y, 20),
    ]
    notify_data(StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_Y_MOTOR, 20, True))

    _expected = [
        (SystemStatusMessageKind.PELLET_Z, 30),
    ]
    notify_data(StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_Z_MOTOR, 30, False))


@pytest.mark.canbus
def test_load_servo_status():
    global _expected

    status = ServoStatus(Target.PELLET_DEVICE, Motor.PELLET_LOAD_SERVO, 40)
    _expected = [
        (SystemStatusMessageKind.PELLET_LOAD, 40),
        (SystemStatusMessageKind.PELLET_LOAD, 40)
    ]
    notify_data(status)


@pytest.mark.canbus
def test_servo_config():
    global _expected

    config = ServoConfig(Target.MAGNET_DEVICE, Motor.PELLET_X_MOTOR, 0, 0, 0,
                         0, 0, 0)

    _expected = [
        (SystemStatusMessageKind.MOTOR_CONFIGURATION, config),
        (SystemStatusMessageKind.ACKNOWLEDGE, None)
    ]
    notify_data(config)


@pytest.mark.canbus
def test_stepper_config():
    global _expected

    config = StepperConfig(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR, 0, 0,
                           0, 0, False)
    _expected = [
        (SystemStatusMessageKind.MOTOR_CONFIGURATION, config),
        (SystemStatusMessageKind.ACKNOWLEDGE, None)
    ]
    notify_data(config)


if __name__ == '__main__':
    test_notify_version()
    test_notify_tare_load_cell()
    test_notify_set_magnet()
    test_notify_set_x()
    test_notify_set_y()
    test_notify_set_z()
    test_notify_set_home()
    test_notify_load_pellet()
    test_notify_send_pellet()
    test_notify_release_pellet()
    test_notify_cover_pellet()
    test_pellet_status()
    test_load_cell_reading()
    test_pressure_reading()
    test_sensor_status()
    test_magnet_digital_inputs()
    test_stepper_status()
    test_load_servo_status()
    test_servo_config()
    test_stepper_config()
