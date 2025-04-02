import pytest

pytestmark = pytest.mark.canbus

try:
    from pyjerrycan import StepperStatus
except (ModuleNotFoundError, TypeError, AttributeError):
    pass

from autotrainer.device import (CanDevice, DeviceApi, CanInterface, GymDeviceMessageKind,
                                HeadFixMessageKind, PelletDeliveryMessageKind, Status,
                                Target, LoadCellReading, PressureReading, SensorStatus,
                                MagnetDigitalInputs, Motor, StepperStatus, ServoStatus,
                                ServoConfig, StepperConfig, MotorSteps
                                )
from autotrainer.core.message import SystemStatusMessageKind

_expected = []


def notify_command(kind, tag, data=None, expected=None, repeat=1):
    global _expected

    if expected is None:
        expected = []
    device = _construction()
    _expected = expected
    _expected.append((GymDeviceMessageKind.ACK, tag))

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
        device = CanDevice()
    except (ModuleNotFoundError, TypeError, AttributeError):
        assert False

    interface = CanInterface()
    # for these tests, do NOT open interface
    interface._set_magnet_address(0x40)
    interface._set_pellet_address(0x01)
    device.api = DeviceApi(interface=interface, message_callback=data_callback)

    return device


@pytest.mark.canbus
def test_notify_version():
    expected = [
        (GymDeviceMessageKind.VERSION, "1.0"),
    ]

    notify_command(GymDeviceMessageKind.VERSION, 101, expected=expected)


@pytest.mark.canbus
def test_notify_tare_load_cell():
    notify_command(HeadFixMessageKind.UPDATE_SCALE_TARE, 102)


@pytest.mark.canbus
def test_notify_set_magnet():
    notify_command(HeadFixMessageKind.SET_MAGNET_INTENSITY, 103, data=3.0)


@pytest.mark.canbus
def test_notify_set_x():
    notify_command(PelletDeliveryMessageKind.SET_X, 10.4, data=4, repeat=2)


@pytest.mark.canbus
def test_notify_set_y():
    notify_command(PelletDeliveryMessageKind.SET_Y, 10.5, data=5, repeat=2)


@pytest.mark.canbus
def test_notify_set_z():
    notify_command(PelletDeliveryMessageKind.SET_Z, 10.6, data=6, repeat=2)


@pytest.mark.canbus
def test_notify_set_home():
    device = _construction()
    device.notify_message(PelletDeliveryMessageKind.SEND_HOME, None)


@pytest.mark.canbus
def test_notify_load_pellet():
    notify_command(PelletDeliveryMessageKind.LOAD_PELLET, 107, repeat=2)


@pytest.mark.canbus
def test_notify_send_pellet():
    notify_command(PelletDeliveryMessageKind.SEND_PELLET, 108, repeat=2)


@pytest.mark.canbus
def test_notify_release_pellet():
    notify_command(PelletDeliveryMessageKind.RELEASE_PELLET, 109)


@pytest.mark.canbus
def test_notify_cover_pellet():
    notify_command(PelletDeliveryMessageKind.COVER_PELLET, 110)


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
        (GymDeviceMessageKind.READ_CONFIG, config)
    ]
    notify_data(config)


@pytest.mark.canbus
def test_stepper_config():
    global _expected

    config = StepperConfig(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR, 0, 0,
                           0, 0, False)
    _expected = [
        (GymDeviceMessageKind.READ_CONFIG, config),
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
