import queue

from autotrainer.device import SerialInterface, HeadFixReader
from autotrainer.device import HeadFix, HeadFixMessageKind
from autotrainer.device import DeviceThread, DeviceThreadMessageKind

from tools.device.head_fix.model.user_settings import UserSettings


class AppModel:
    def __init__(self):
        self._user_settings = UserSettings()

        self._msg_queue = queue.Queue()

        self._device_thread = None

        self._head_fix_reader = None

        self._is_connected = False

        self._ports = list()

        self.refresh_ports()

    @property
    def user_settings(self) -> UserSettings:
        return self._user_settings

    @property
    def ports(self):
        return self._ports

    @property
    def is_connected(self):
        return self._is_connected

    @property
    def head_fix_reader(self):
        return self._head_fix_reader

    def refresh_ports(self):
        self._ports = SerialInterface.refresh_ports()

    def update_position(self, value: int):
        self._device_thread.send_message(HeadFixMessageKind.SERVO, str(value))

    def tare(self):
        self._device_thread.send_message(HeadFixMessageKind.UPDATE_TARE)

    def connect_to_device(self):
        self._device_thread.send_message(DeviceThreadMessageKind.CONNECT)

        self._device_thread.send_message(HeadFixMessageKind.VERSION)

        self._is_connected = True

    def disconnect_from_device(self):
        self._device_thread.send_message(DeviceThreadMessageKind.DISCONNECT)

        self._is_connected = False

    def on_activated(self):
        device_interface = SerialInterface(self._user_settings.port)

        self._head_fix_reader = HeadFixReader(self._msg_queue)

        self._head_fix_reader.start()

        head_fix = HeadFix(buffer_size=10)

        self._device_thread = DeviceThread(head_fix, device_interface, self._msg_queue)
        self._device_thread.name = "head-fix"

        self._device_thread.start()

    def on_close(self):
        self._msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))
        self._device_thread.send_message(DeviceThreadMessageKind.TERMINATE)
