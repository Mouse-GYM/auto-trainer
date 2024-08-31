import queue

from autotrainer.core.project import ProjectInterval
from autotrainer.device import SerialInterface, HeadFixReader, GymDeviceMessageKind
from autotrainer.device import HeadFix, HeadFixMessageKind
from autotrainer.device import DeviceThread, DeviceThreadMessageKind

from tools.head_fix.model.user_settings import UserSettings


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

    def set_stream_enabled(self, enable: bool):
        if enable:
            self._set_stream_enable()
        else:
            self._device_thread.send_message(HeadFixMessageKind.STREAM_STOP)

        self._user_settings.stream_enabled = enable

    def connect_to_device(self):
        if len(self._user_settings.port) == 0:
            return

        device_interface = SerialInterface(self._user_settings.port)

        self._device_thread = DeviceThread(HeadFix(buffer_size=10), device_interface, self._msg_queue)
        self._device_thread.name = "head-fix"

        self._device_thread.start()

        self._device_thread.send_message(DeviceThreadMessageKind.CONNECT)

        self._device_thread.send_message(GymDeviceMessageKind.VERSION)

        if self._user_settings.stream_enabled:
            self._set_stream_enable()

        self._is_connected = True

    def disconnect_from_device(self):
        if self._is_connected:
            if self._device_thread is not None:
                self._device_thread.send_message(DeviceThreadMessageKind.DISCONNECT)
                self._device_thread.send_message(DeviceThreadMessageKind.TERMINATE)
                self._device_thread = None

            self._is_connected = False

    def on_activated(self):
        self._head_fix_reader = HeadFixReader(self._msg_queue)
        self._head_fix_reader.interval = ProjectInterval.HOUR
        self._head_fix_reader.start()

    def on_close(self):
        self.disconnect_from_device()
        self._msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))
        if self._device_thread is not None:
            self._device_thread.send_message(DeviceThreadMessageKind.TERMINATE)

    def _set_stream_enable(self):
        if self._device_thread is not None:
            self._device_thread.send_message(HeadFixMessageKind.STREAM_START)
        if self._head_fix_reader is not None:
            self._msg_queue.put((HeadFixMessageKind.STREAM_START, None))
