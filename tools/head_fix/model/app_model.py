import logging
import queue

from autotrainer.core import ObservableObject, ProjectInterval, SystemMessageHandler, \
    SystemCommandKind
from autotrainer.device import CanDevice, CAN_IDENTIFIER, HAVE_CAN_DEVICE
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
        self._message_handler.property_changed += self.message_handler_property_changed
        self._message_handler.ack_received += self.reader_ack_received

        self._analysis = self._message_handler.analysis
        self._analysis.interval = ProjectInterval.HOUR
        self._analysis.tare_callback = self.tare

        self._is_connected = False

        self._firmware_version = ""

        self._magnet_intensity = -1.0

    @property
    def user_settings(self) -> UserSettings:
        return self._user_settings

    @property
    def is_connected(self):
        return self._is_connected

    @property
    def firmware_version(self) -> str:
        return self._firmware_version

    @firmware_version.setter
    def firmware_version(self, value):
        self._firmware_version = self._on_property_changed("firmware_version", value,
                                                           self._firmware_version)

    @property
    def magnet_intensity(self) -> float:
        return self._magnet_intensity

    @magnet_intensity.setter
    def magnet_intensity(self, value: float):
        self._magnet_intensity = self._on_property_changed("magnet_intensity", value,
                                                           self._magnet_intensity)

    @property
    def message_handler(self):
        return self._message_handler

    @property
    def analysis(self):
        return self._analysis

    def set_position(self, value: float):
        if self._device_connection is not None:
            self._device_connection.send_message(SystemCommandKind.SET_MAGNET_INTENSITY, value)

    def tare(self):
        if self._device_connection is not None:
            self._device_connection.send_message(SystemCommandKind.UPDATE_SCALE_TARE)
        else:
            logger.warning("attempt to tare when device thread is not initialized")

    def set_stream_enabled(self, enable: bool):
        if enable:
            self._enable_data_stream()
        else:
            if self._device_connection is not None:
                self._device_connection.send_message(SystemCommandKind.STREAM_STOP)

        self._user_settings.stream_enabled = enable

    def connect_to_device(self):
        if len(self._user_settings.port) == 0:
            return

        if self._user_settings.port == CAN_IDENTIFIER:
            # This is specific to wanting to be able to test UI changes w/the emulation interface, which is not
            # configured to generate messages as frequently as the real device.
            buffer_size = 10 if HAVE_CAN_DEVICE else 1
            self._device_connection = DeviceConnection(CanDevice(buffer_size=buffer_size),
                                                       self._message_handler.input_queue)
        else:
            self._device_connection = DeviceConnection(
                HeadFix(port=self._user_settings.port, buffer_size=10),
                self._message_handler.input_queue)

        self._device_connection.name = "head-fix"

        self._device_connection.start()

        self._device_connection.send_message(DeviceThreadMessageKind.CONNECT)

        self._device_connection.send_message(SystemCommandKind.REQUEST_VERSION)

        if self._user_settings.stream_enabled:
            self._enable_data_stream()

        self._is_connected = True

    def disconnect_from_device(self):
        if self._is_connected:
            # End DeviceConnection for this connection.  Do not kill the message handler which is connection agnostic.
            if self._device_connection is not None:
                self._device_connection.send_message(
                    (DeviceThreadMessageKind.DISCONNECT, None, None))
                self._device_connection.request_terminate()
                self._device_connection = None

            self._is_connected = False

            self._firmware_version = ""

    def on_activated(self):
        self._message_handler.start()

    def on_close(self):
        self.disconnect_from_device()

        # End all threads so application exits cleanly.
        if self._device_connection is not None:
            self._device_connection.request_terminate()
        if self._message_handler is not None:
            self._message_handler.request_terminate()

    def message_handler_property_changed(self, name: str, value, _old_value):
        if name == SystemMessageHandler.FIRMWARE_VERSION:
            self.firmware_version = value
        elif name == "head_magnet_intensity":
            self.magnet_intensity = value

    @staticmethod
    def reader_ack_received(ack):
        logger.info(f"ack context received: {ack}")

    def _enable_data_stream(self):
        if self._device_connection is not None:
            self._device_connection.send_message(SystemCommandKind.STREAM_START)
        if self._message_handler is not None and self._message_handler.input_queue is not None:
            self._message_handler.input_queue.put((SystemCommandKind.STREAM_START, None))
