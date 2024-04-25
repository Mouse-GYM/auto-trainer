import queue

from PySide6.QtCore import QThread

from autotrainer.serial_interface import SerialInterface
from autotrainer.head_fix import HeadFix, HeadFixMessageKind
from autotrainer.device_thread import DeviceThread, DeviceThreadMessageKind
from autotrainer.head_fix_measurement_reader import HeadFixMeasurementReader

from tools.device.head_fix.model.user_settings import UserSettings


class AppModel:
    def __init__(self):
        self._user_settings = UserSettings()

        self._cmd_queue = queue.Queue()
        self._msg_queue = queue.Queue()
        self._device_thread = None

        self._measurement_thread = QThread()
        self._measurement_worker = HeadFixMeasurementReader(self._msg_queue)
        self._measurement_worker.moveToThread(self._measurement_thread)
        self._measurement_thread.started.connect(self._measurement_worker.process)

        self._is_connected = False

        self._ports = list()

        self.refresh_ports()

    @property
    def user_settings(self) -> UserSettings:
        return self._user_settings

    @property
    def measurements(self) -> HeadFixMeasurementReader:
        return self._measurement_worker

    @property
    def ports(self):
        return self._ports

    @property
    def is_connected(self):
        return self._is_connected

    def refresh_ports(self):
        self._ports = SerialInterface.list_ports()

    def update_position(self, value: int):
        self._cmd_queue.put((HeadFixMessageKind.SERVO, str(value)))

    def tare(self):
        self._cmd_queue.put((HeadFixMessageKind.UPDATE_TARE, ""))

    def connect_to_device(self):
        device_interface = SerialInterface(self._user_settings.port)

        head_fix = HeadFix(device_interface, 10)

        self._device_thread = DeviceThread(head_fix, device_interface, self._cmd_queue, self._msg_queue)

        self._device_thread.start()

        self._measurement_thread.start()

        self._is_connected = True

    def disconnect_from_device(self):
        self._cmd_queue.put((DeviceThreadMessageKind.TERMINATE, None))

        self._is_connected = False

    def on_close(self):
        self.disconnect_from_device()
        self._msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))
