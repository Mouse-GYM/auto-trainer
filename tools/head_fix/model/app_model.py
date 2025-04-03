import logging
import queue

from autotrainer.core import ObservableObject, ProjectInterval, DeviceReader, HeadFixReader
from autotrainer.device import SerialInterface, GymDeviceMessageKind, CanDevice, HAVE_CAN_DEVICE
from autotrainer.device import HeadFix, HeadFixMessageKind
from autotrainer.device import DeviceThread, DeviceApi, DeviceThreadMessageKind

from tools.head_fix.model.user_settings import UserSettings

logger = logging.getLogger(__name__)


class AppModel(ObservableObject):
    def __init__(self):
        super().__init__()
        self._user_settings = UserSettings()

        self._msg_queue = queue.Queue()

        self._device_thread = None

        self._head_fix_reader = HeadFixReader(self._msg_queue)
        self._head_fix_reader.interval = ProjectInterval.HOUR
        self._head_fix_reader.property_changed += self.reader_property_changed
        self._head_fix_reader.ack_received += self.reader_ack_received
        self._head_fix_reader.tare_callback = self.tare

        self._is_connected = False

        self._firmware_version = ""

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
    def firmware_version(self) -> str:
        return self._firmware_version

    @firmware_version.setter
    def firmware_version(self, value):
        self._firmware_version = self._on_property_changed(DeviceReader.FIRMWARE_VERSION, value,
                                                           self._firmware_version)

    @property
    def head_fix_reader(self):
        return self._head_fix_reader

    def refresh_ports(self):
        self._ports = SerialInterface.refresh_ports()

        if HAVE_CAN_DEVICE:
            self._ports.insert(0, "CAN bus")

        return self._ports

    def set_position(self, value: float):
        self._device_thread.send_message(HeadFixMessageKind.SET_MAGNET_INTENSITY, value)

    def tare(self):
        if self._device_thread is not None:
            self._device_thread.send_message(HeadFixMessageKind.UPDATE_SCALE_TARE)
        else:
            logger.warning("attempt to tare when device thread is not initialized")

    def set_stream_enabled(self, enable: bool):
        if enable:
            self._enable_data_stream()
        else:
            if self._device_thread is not None:
                self._device_thread.send_message(HeadFixMessageKind.STREAM_STOP)

        self._user_settings.stream_enabled = enable

    def connect_to_device(self):
        if len(self._user_settings.port) == 0:
            return

        if self._user_settings.port == "CAN bus":
            self._device_thread = DeviceThread(CanDevice(DeviceApi(
                message_queue=self._msg_queue), buffer_size=10))

        else:
            self._device_thread = DeviceThread(HeadFix(port=self._user_settings.port,
                                                       api=DeviceApi(message_queue=self._msg_queue),
                                                       buffer_size=10))

        self._device_thread.name = "head-fix"

        self._device_thread.start()

        self._device_thread.send_message(DeviceThreadMessageKind.CONNECT)

        self._device_thread.send_message(GymDeviceMessageKind.VERSION)

        if self._user_settings.stream_enabled:
            self._enable_data_stream()

        self._is_connected = True

    def disconnect_from_device(self):
        if self._is_connected:
            if self._device_thread is not None:
                self._device_thread.send_message(DeviceThreadMessageKind.DISCONNECT)
                self._device_thread.send_message(DeviceThreadMessageKind.TERMINATE)
                self._device_thread = None

            self._is_connected = False

    def on_activated(self):
        self._head_fix_reader.start()

    def on_close(self):
        self.disconnect_from_device()
        self._msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))
        if self._device_thread is not None:
            self._device_thread.send_message(DeviceThreadMessageKind.TERMINATE)

    def reader_property_changed(self, name: str, value, _old_value):
        if name == DeviceReader.FIRMWARE_VERSION:
            self.firmware_version = value

    @staticmethod
    def reader_ack_received(ack):
        logger.info(f"ack context received: {ack}")

    def _enable_data_stream(self):
        if self._device_thread is not None:
            self._device_thread.send_message(HeadFixMessageKind.STREAM_START)
        if self._head_fix_reader is not None:
            self._msg_queue.put((HeadFixMessageKind.STREAM_START, None))
