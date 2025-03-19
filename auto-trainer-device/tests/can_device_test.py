import unittest
import functools

from pyjerrycan import StepperStatus

from autotrainer.device import (CanDevice, DeviceApi, CanInterface, GymDeviceMessageKind,
                                HeadFixMessageKind, PelletDeliveryMessageKind, MotorSteps, Status,
                                Target, LoadCellReading, PressureReading, SensorStatus,
                                MagnetDigitalInputs, Motor, StepperStatus, ServoStatus,
                                ServoConfig, StepperConfig
                                )


def notify_command(self, kind, tag, data=None, expected=None, repeat=1):
    if expected is None:
        expected = []
    device = self.test_set_api()
    self._expected = expected
    self._expected.append((GymDeviceMessageKind.ACK, tag))

    for i in range(repeat):
        device.notify_message(kind, data, tag)

    self.assertEqual(len(self._expected), 0)


def notify_data(self, data):
    device = self.test_set_api()
    device.notify_data([data])


class MyTestCase(unittest.TestCase):
    _expected = []

    def data_callback(self, kind: int, response: object):
        if len(self._expected) == 0:
            self.fail()

        k, r = self._expected.pop(0)

        self.assertEqual(kind, k)
        self.assertEqual(response, r)

    def test_construction(self) -> CanDevice:
        try:
            device = CanDevice()
            return device
        except:
            self.fail()

    def test_set_api(self) -> CanDevice:
        device = self.test_construction()
        interface = CanInterface()
        # for these tests, do NOT open interface
        interface.set_magnet_address(0x40)
        interface.set_pellet_address(0x01)
        device.api = DeviceApi(interface=interface, message_callback=self.data_callback)
        return device

    def test_notify_version(self):
        expected = [
            (GymDeviceMessageKind.VERSION, "1.0"),
        ]

        notify_command(self, GymDeviceMessageKind.VERSION, 101, expected=expected)

    def test_notify_tare_load_cell(self):
        notify_command(self, HeadFixMessageKind.UPDATE_SCALE_TARE, 102)

    def test_notify_set_magnet(self):
        notify_command(self, HeadFixMessageKind.MAGNET_INTENSITY, 103, data=3)

    def test_notify_set_x(self):
        notify_command(self, PelletDeliveryMessageKind.SET_X, 104, data=4, repeat=2)

    def test_notify_set_y(self):
        notify_command(self, PelletDeliveryMessageKind.SET_Y, 105, data=5, repeat=2)

    def test_notify_set_z(self):
        notify_command(self, PelletDeliveryMessageKind.SET_Z, 105, data=5, repeat=2)

    def test_notify_set_home(self):
        notify_command(self, PelletDeliveryMessageKind.SEND_HOME, 106, repeat=2)

    def test_notify_load_pellet(self):
        notify_command(self, PelletDeliveryMessageKind.LOAD_PELLET, 107, repeat=2)

    def test_notify_send_pellet(self):
        notify_command(self, PelletDeliveryMessageKind.SEND_PELLET, 108, repeat=2)

    def test_notify_release_pellet(self):
        notify_command(self, PelletDeliveryMessageKind.RELEASE_PELLET, 109)

    def test_notify_cover_pellet(self):
        notify_command(self, PelletDeliveryMessageKind.COVER_PELLET, 110)

    def test_pellet_status(self):
        notify_data(self, Status(Target.MAGNET_DEVICE))

    def test_load_cell_reading(self):
        notify_data(self, LoadCellReading(Target.MAGNET_DEVICE, 13))

    def test_pressure_reading(self):
        notify_data(self, PressureReading(Target.MAGNET_DEVICE, 14))

    def test_sensor_status(self):
        notify_data(self, SensorStatus(Target.PELLET_DEVICE, 27.3, 64.2))

    def test_magnet_digital_inputs(self):
        notify_data(self, MagnetDigitalInputs(Target.MAGNET_DEVICE, False, True))

    def test_stepper_status(self):
        self._expected = [
            (PelletDeliveryMessageKind.UPDATE_X, 10),
        ]
        notify_data(self, StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR, 10, False))

        self._expected = [
            (PelletDeliveryMessageKind.UPDATE_Y, 20),
        ]
        notify_data(self, StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_Y_MOTOR, 20, True))

        self._expected = [
            (PelletDeliveryMessageKind.UPDATE_Z, 30),
        ]
        notify_data(self, StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_Z_MOTOR, 30, False))

    def test_load_servo_status(self):
        status = ServoStatus(Target.PELLET_DEVICE, Motor.PELLET_LOAD_SERVO, 40)
        self._expected = [
            (PelletDeliveryMessageKind.UPDATE_LOAD, 40)
        ]
        notify_data(self, status)

    def test_servo_config(self):
        config = ServoConfig(Target.MAGNET_DEVICE, Motor.PELLET_X_MOTOR, False, 0, 0, 0,
                             0, 0, 0)

        self._expected = [
            (GymDeviceMessageKind.READ_CONFIG, config)
        ]
        notify_data(self, config)

    def test_stepper_config(self):
        config = StepperConfig(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR, False, 0, 0,
                               0, 0)
        self._expected = [
            (GymDeviceMessageKind.READ_CONFIG, config),
        ]

        notify_data(self, config)


if __name__ == '__main__':
    unittest.main()
