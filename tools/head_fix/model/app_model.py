import logging
import queue

from autotrainer.core import ObservableObject, ProjectInterval, SystemMessageHandler
from autotrainer.device import GymDeviceMessageKind, CanDevice, get_available_hardware, HeadFixMessageKind
from autotrainer.device import HeadFix
from autotrainer.device import DeviceConnection, DeviceThreadMessageKind

from tools.head_fix.model.user_settings import UserSettings

logger = logging.getLogger(__name__)


class AppModel(ObservableObject):
    def __init__(self, allow_can_emulation: bool = False):
        super().__init__()

        self._allow_can_emulation = allow_can_emulation

        self._user_settings = UserSettings()

        self._device_connection = None

        self._message_handler = SystemMessageHandler(queue.Queue())
        self._message_handler.ack_received += self.reader_ack_received

        self._analysis = self._message_handler.analysis
        self._analysis.interval = ProjectInterval.HOUR
        self._analysis.property_changed += self.reader_property_changed
        self._analysis.tare_callback = self.tare

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
        self._firmware_version = self._on_property_changed(SystemMessageHandler.FIRMWARE_VERSION, value,
                                                           self._firmware_version)

    @property
    def message_handler(self):
        return self._message_handler

    @property
    def analysis(self):
        return self._analysis

    def refresh_ports(self):
        self._ports = get_available_hardware(allow_can_emulation=self._allow_can_emulation)

        return self._ports

    def set_position(self, value: float):
        if self._device_connection is not None:
            self._device_connection.send_message(HeadFixMessageKind.SET_MAGNET_INTENSITY, value)

    def tare(self):
        if self._device_connection is not None:
            self._device_connection.send_message(HeadFixMessageKind.UPDATE_SCALE_TARE)
        else:
            logger.warning("attempt to tare when device thread is not initialized")

    def set_stream_enabled(self, enable: bool):
        if enable:
            self._enable_data_stream()
        else:
            if self._device_connection is not None:
                self._device_connection.send_message(HeadFixMessageKind.STREAM_STOP)

        self._user_settings.stream_enabled = enable

    def connect_to_device(self):
        if len(self._user_settings.port) == 0:
            return

        if self._user_settings.port == "CAN bus":
            self._device_connection = DeviceConnection(CanDevice(buffer_size=10), self._message_handler.input_queue)
        else:
            self._device_connection = DeviceConnection(HeadFix(port=self._user_settings.port, buffer_size=10),
                                                       self._message_handler.input_queue)

        self._device_connection.name = "head-fix"

        self._device_connection.start()

        self._device_connection.send_message(DeviceThreadMessageKind.CONNECT)

        self._device_connection.send_message(GymDeviceMessageKind.VERSION)

        if self._user_settings.stream_enabled:
            self._enable_data_stream()

        self._is_connected = True

    def disconnect_from_device(self):
        if self._is_connected:
            # End DeviceConnection for this connection.  Do not kill the message handler which is connection agnostic.
            if self._device_connection is not None:
                self._device_connection.send_message((DeviceThreadMessageKind.DISCONNECT, None, None))
                self._device_connection.request_terminate()
                self._device_connection = None

            self._is_connected = False

    def on_activated(self):
        self._message_handler.start()

    def on_close(self):
        self.disconnect_from_device()

        # End all threads so application exits cleanly.
        if self._device_connection is not None:
            self._device_connection.request_terminate()
        if self._message_handler is not None:
            self._message_handler.request_terminate()

    def reader_property_changed(self, name: str, value, _old_value):
        if name == SystemMessageHandler.FIRMWARE_VERSION:
            self.firmware_version = value

    @staticmethod
    def reader_ack_received(ack):
        logger.info(f"ack context received: {ack}")

    def _enable_data_stream(self):
        if self._device_connection is not None:
            self._device_connection.send_message(HeadFixMessageKind.STREAM_START)
        if self._message_handler is not None and self._message_handler.input_queue is not None:
            self._message_handler.input_queue.put((HeadFixMessageKind.STREAM_START, None))
