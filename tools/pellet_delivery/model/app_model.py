import logging
import queue
import uuid

from autotrainer.core import ObservableObject, DeviceReader, PelletReader
from autotrainer.device import GymDeviceMessageKind, CanDevice, get_available_hardware, PelletDeliveryMessageKind, \
    CAN_IDENTIFIER
from autotrainer.device import PelletDelivery
from autotrainer.device import DeviceConnection, DeviceThreadMessageKind

from tools.pellet_delivery.model.user_settings import UserSettings

logger = logging.getLogger(__name__)

# TODO: This is just to see if the behavior is correct.  They should end up somewhere that any application or script can
#  access.
_anshutz_travel_limits = {
    "x": (-10, 10),
    "y": (-10, 10),
    "z": (-10, 10),
}

_alogus_travel_limits = {
    "x": (0, 27),
    "y": (0, 27),
    "z": (0, 27),
}


class AppModel(ObservableObject):
    def __init__(self):
        super().__init__()

        self._user_settings = UserSettings()

        self._device_connection = None

        self._pellet_reader = PelletReader(queue.Queue())
        self._pellet_reader.property_changed += self.reader_property_changed
        self._pellet_reader.ack_received += self.reader_ack_received

        self._is_connected = False

        self._firmware_version = ""

        # The values the device is reporting - not a requested value.
        self._x = None
        self._y = None
        self._z = None
        self._load_arm = None
        self._cover_arm = None

        self._command_pending = False
        self._last_command = None

        self._ports = list()

        self.refresh_ports()

        self._travel_limits = _anshutz_travel_limits

    @property
    def user_settings(self) -> UserSettings:
        return self._user_settings

    @property
    def ports(self):
        return self._ports

    @property
    def is_connected(self):
        return self._is_connected

    @is_connected.setter
    def is_connected(self, value):
        self._is_connected = self._on_property_changed("is_connected", value, self._is_connected)

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
    def load_arm(self):
        return self._load_arm

    @load_arm.setter
    def load_arm(self, value):
        self._load_arm = self._on_property_changed("load_arm", value, self._load_arm)

    @property
    def cover_arm(self):
        return self._cover_arm

    @cover_arm.setter
    def cover_arm(self, value):
        self._cover_arm = self._on_property_changed("cover_arm", value, self._cover_arm)

    @property
    def travel_limits(self):
        return self._travel_limits

    @travel_limits.setter
    def travel_limits(self, value):
        self._travel_limits = self._on_property_changed("travel_limits", value, self._travel_limits)

    @property
    def command_pending(self):
        return self._command_pending

    @command_pending.setter
    def command_pending(self, value):
        self._command_pending = self._on_property_changed("command_pending", value,
                                                          self._command_pending)

    def refresh_ports(self):
        self._ports = get_available_hardware()

        return self._ports

    def send_home(self):
        self._send_command(PelletDeliveryMessageKind.SEND_HOME, context=uuid.uuid4())

    def load_pellet(self):
        self._send_command(PelletDeliveryMessageKind.LOAD_PELLET, context=uuid.uuid4())

    def send_pellet(self):
        self._send_command(PelletDeliveryMessageKind.SEND_PELLET, context=uuid.uuid4())

    def release_pellet(self):
        self._send_command(PelletDeliveryMessageKind.RELEASE_PELLET, context=uuid.uuid4())

    def cover_pellet(self):
        self._send_command(PelletDeliveryMessageKind.COVER_PELLET, context=uuid.uuid4())

    def set_x(self, value: int):
        self._send_command(PelletDeliveryMessageKind.SET_X, value, context=uuid.uuid4())

    def set_y(self, value: int):
        self._send_command(PelletDeliveryMessageKind.SET_Y, value, context=uuid.uuid4())

    def set_z(self, value: int):
        self._send_command(PelletDeliveryMessageKind.SET_Z, value, context=uuid.uuid4())

    def connect_to_device(self):
        if len(self._user_settings.port) == 0:
            return

        if self._user_settings.port == CAN_IDENTIFIER:
            self._device_connection = DeviceConnection(CanDevice(), self._pellet_reader.input_queue, name="pellet-can")
            self.travel_limits = _alogus_travel_limits
        else:
            self._device_connection = DeviceConnection(PelletDelivery(self._user_settings.port),
                                                       self._pellet_reader.input_queue, name="pellet_serial")
            self.travel_limits = _anshutz_travel_limits

        self._device_connection.start()

        self._send_command(DeviceThreadMessageKind.CONNECT)

        self._send_command(GymDeviceMessageKind.VERSION)

        self.is_connected = True

    def disconnect_from_device(self):
        if self._is_connected:
            # End DeviceConnection for this connection.  Do not kill pellet reader which is connection agnostic.
            if self._device_connection is not None:
                self._send_command(DeviceThreadMessageKind.DISCONNECT)
                self._device_connection.request_terminate()
                self._device_connection = None

            self.is_connected = False

        self.firmware_version = ""

    def on_activated(self):
        self._pellet_reader.start()

    def on_close(self):
        self.disconnect_from_device()

        # End all threads so application exits cleanly.
        if self._device_connection is not None:
            self._device_connection.request_terminate()
        if self._pellet_reader is not None:
            self._pellet_reader.request_terminate()

    def reader_property_changed(self, name: str, value, _old_value):
        if name == DeviceReader.FIRMWARE_VERSION:
            self.firmware_version = value
        elif name == "device_x":
            self.x = value
        elif name == "device_y":
            self.y = value
        elif name == "device_z":
            self.z = value
        elif name == "load_angle":
            self.load_arm = value
        elif name == "cover_angle":
            self.cover_arm = value

    def reader_ack_received(self, ack):
        logger.info(f"ack context received: {ack}")

        if self._last_command is not None and ack == self._last_command:
            self._last_command = None
            self.command_pending = False

    def _send_command(self, message, data=None, context=None):
        if self._last_command is not None:
            logger.debug("ignoring command while existing command is in process")
            return

        if context is not None:
            # If not planning to confirm the response token, don't block the UI.
            self.command_pending = True

        self._last_command = context

        if context is not None:
            logger.debug(f"sending message with context: {context}")

        if self._device_connection is not None:
            self._device_connection.send_message(message, data, context)
