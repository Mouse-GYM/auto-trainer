import logging
import queue
import uuid

from autotrainer.core import ObservableObject, DeviceReader, PelletReader
from autotrainer.device import SerialInterface, GymDeviceMessageKind, CanDevice, HAVE_CAN_DEVICE
from autotrainer.device import PelletDelivery, PelletDeliveryMessageKind
from autotrainer.device import DeviceThread, DeviceThreadMessageKind

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

        self._x = None
        self._y = None
        self._z = None

        self._command_pending = False

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
        self._firmware_version = self._on_property_changed("firmware_version", value,
                                                           self._firmware_version)

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, value):
        self._x = self._on_property_changed("x", value, self._x)

    @property
    def y(self):
        return self._y

    @y.setter
    def y(self, value):
        self._y = self._on_property_changed("y", value, self._y)

    @property
    def z(self):
        return self._z

    @z.setter
    def z(self, value):
        self._z = self._on_property_changed("z", value, self._z)

    @property
    def command_pending(self):
        return self._command_pending

    @command_pending.setter
    def command_pending(self, value):
        self._command_pending = self._on_property_changed("command_pending", value,
                                                          self._command_pending)

    def refresh_ports(self):
        self._ports = SerialInterface.refresh_ports()

        if HAVE_CAN_DEVICE:
            self._ports.insert(0, "CAN bus")

        return self._ports

    def send_home(self):
        self.command_pending = True
        self._send_command(PelletDeliveryMessageKind.SEND_HOME, context=uuid.uuid4())

    def load_pellet(self):
        self.command_pending = True
        self._send_command(PelletDeliveryMessageKind.LOAD_PELLET, context=uuid.uuid4())

    def send_pellet(self):
        self.command_pending = True
        self._send_command(PelletDeliveryMessageKind.SEND_PELLET, context=uuid.uuid4())

    def release_pellet(self):
        self.command_pending = True
        self._send_command(PelletDeliveryMessageKind.RELEASE_PELLET, context=uuid.uuid4())

    def cover_pellet(self):
        self.command_pending = True
        self._send_command(PelletDeliveryMessageKind.COVER_PELLET, context=uuid.uuid4())

    def set_x(self, value: int):
        self.command_pending = True
        self._send_command(PelletDeliveryMessageKind.SET_X, value, context=uuid.uuid4())

    def set_y(self, value: int):
        self.command_pending = True
        self._send_command(PelletDeliveryMessageKind.SET_Y, value, context=uuid.uuid4())

    def set_z(self, value: int):
        self.command_pending = True
        self._send_command(PelletDeliveryMessageKind.SET_Z, value, context=uuid.uuid4())

    def connect_to_device(self):
        if len(self._user_settings.port) == 0:
            return

        if self._user_settings.port == "CAN bus":
            self._device_thread = DeviceThread(CanDevice(), message_queue=self._msg_queue)
        else:
            self._device_thread = DeviceThread(PelletDelivery(self._user_settings.port),
                                               message_queue=self._msg_queue)

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
        elif name == "device_x":
            self.x = value
        elif name == "device_y":
            self.y = value
        elif name == "device_z":
            self.z = value

    # noinspection PyMethodMayBeStatic
    def reader_ack_received(self, ack):
        logger.info(f"ack context received: {ack}")
        self.command_pending = False

    def _send_command(self, message, data=None, context=None):
        if context is not None:
            logger.debug(f"sending message with context: {context}")

        if self._device_thread is not None:
            self._device_thread.send_message(message, data, context)
