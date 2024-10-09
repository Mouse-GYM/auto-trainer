import logging
import queue
import uuid

from autotrainer.core import ObservableObject
from autotrainer.device import SerialInterface, GymDeviceMessageKind
from autotrainer.device import PelletDelivery, PelletDeliveryMessageKind
from autotrainer.device import DeviceThread, DeviceThreadMessageKind
from autotrainer.device import PelletReader
from autotrainer.device.device_reader import DeviceReader

from tools.pellet_delivery.model.user_settings import UserSettings

logger = logging.getLogger(__name__)


class AppModel(ObservableObject):
    def __init__(self):
        super().__init__()

        self._user_settings = UserSettings()

        self._msg_queue = queue.Queue()

        self._device_thread = None

        self._pellet_reader = PelletReader(self._msg_queue)
        self._pellet_reader.property_changed += self.reader_property_changed
        self._pellet_reader.ack_received += self.reader_ack_received

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
        self._firmware_version = self._on_property_changed("firmware_version", value, self._firmware_version)

    def refresh_ports(self):
        self._ports = SerialInterface.refresh_ports()

    def send_home(self):
        self._send_command(PelletDeliveryMessageKind.SEND_HOME, context=uuid.uuid4())

    def load_pellet(self):
        self._send_command(PelletDeliveryMessageKind.LOAD_PELLET, context=uuid.uuid4())

    def send_pellet(self):
        self._send_command(PelletDeliveryMessageKind.SEND_PELLET, context=uuid.uuid4())

    def release_pellet(self):
        self._send_command(PelletDeliveryMessageKind.RELEASE_PELLET, context=uuid.uuid4())

    def set_x(self, value: int):
        self._send_command(PelletDeliveryMessageKind.SET_X, value, context=uuid.uuid4())

    def set_y(self, value: int):
        self._send_command(PelletDeliveryMessageKind.SET_Y, value, context=uuid.uuid4())

    def set_z(self, value: int):
        self._send_command(PelletDeliveryMessageKind.SET_Z, value, context=uuid.uuid4())

    def connect_to_device(self):
        if len(self._user_settings.port) == 0:
            return

        device_interface = SerialInterface(self._user_settings.port)

        self._device_thread = DeviceThread(PelletDelivery(), device_interface, self._msg_queue)
        self._device_thread.name = "pellet"

        self._device_thread.start()

        self._send_command(DeviceThreadMessageKind.CONNECT)

        self._send_command(GymDeviceMessageKind.VERSION)

        self._is_connected = True

    def disconnect_from_device(self):
        if self._is_connected:
            if self._device_thread is not None:
                self._send_command(DeviceThreadMessageKind.DISCONNECT)
                self._send_command(DeviceThreadMessageKind.TERMINATE)
                self._device_thread = None

            self._is_connected = False

    def on_activated(self):
        self._pellet_reader.start()

    def on_close(self):
        self.disconnect_from_device()
        self._send_command(DeviceThreadMessageKind.TERMINATE)
        self._msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))

    def reader_property_changed(self, name: str, value, _old_value):
        if name == DeviceReader.FIRMWARE_VERSION:
            self.firmware_version = value

    # noinspection PyMethodMayBeStatic
    def reader_ack_received(self, ack):
        logger.info(f"ack context received: {ack}")

    def _send_command(self, message, data=None, context=None):
        if context is not None:
            logger.debug(f"sending message with context: {context}")

        if self._device_thread is not None:
            self._device_thread.send_message(message, data, context)
