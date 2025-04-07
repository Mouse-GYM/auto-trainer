import logging
import queue
import uuid
from typing import Optional

from autotrainer.core import ObservableObject, ProjectInfo, SystemMessageHandler, MessageHandler, SystemCommandKind
from autotrainer.device import get_available_hardware
from autotrainer.device import PelletDelivery
from autotrainer.device import DeviceConnection, DeviceThreadMessageKind

logger = logging.getLogger(__name__)


class PelletDeliveryModel(ObservableObject):
    def __init__(self, allow_can_emulation: bool = False):
        super().__init__()

        self._allow_can_emulation = allow_can_emulation

        self._message_queue = queue.Queue()

        self._port = None

        self._device_thread = None

        self._message_handler = None
        self._message_handler = SystemMessageHandler(self._message_queue)

        self._is_connected = False

        self._x = 0

        self._y = 0

        self._z = 0

        self._project: Optional[ProjectInfo] = None

    @property
    def project(self) -> ProjectInfo:
        return self._project

    @project.setter
    def project(self, value: ProjectInfo) -> None:
        self._project = value

    @property
    def port(self) -> str:
        return self._port

    @port.setter
    def port(self, value: str):
        self._port = self._on_property_changed("port", value, self._port)

    @property
    def is_connected(self):
        return self._is_connected

    @property
    def x(self) -> int:
        return self._x

    @property
    def y(self) -> int:
        return self._y

    @property
    def z(self) -> int:
        return self._z

    @property
    def pellet_reader(self) -> MessageHandler:
        return self._message_handler

    def set_x(self, value: int) -> object:
        self._x = self._on_property_changed("x", value, self._x)

        return self._send_with_token(SystemCommandKind.SET_X, value)

    def set_y(self, value: int) -> object:
        self._y = self._on_property_changed("y", value, self._y)

        return self._send_with_token(SystemCommandKind.SET_Y, value)

    def set_z(self, value: int) -> object:
        self._z = self._on_property_changed("z", value, self._z)

        return self._send_with_token(SystemCommandKind.SET_Z, value)

    def send_home(self) -> object:
        return self._send_with_token(SystemCommandKind.SEND_HOME)

    def load_pellet(self) -> object:
        return self._send_with_token(SystemCommandKind.LOAD_PELLET)

    def send_pellet(self) -> object:
        return self._send_with_token(SystemCommandKind.SEND_PELLET)

    def release_pellet(self) -> object:
        return self._send_with_token(SystemCommandKind.RELEASE_PELLET)

    def cover_pellet(self) -> object:
        return self._send_with_token(SystemCommandKind.COVER_PELLET)

    def refresh_ports(self):
        return get_available_hardware(allow_can_emulation=self._allow_can_emulation)

    def connect_to_device(self):
        if not self.port or len(self.port) == 0:
            return

        self._device_thread = DeviceConnection(PelletDelivery(self.port), self._message_queue)
        self._device_thread.name = "pellet"

        self._device_thread.start()

        self._device_thread.send_message(DeviceThreadMessageKind.CONNECT)

        # For the v1 hardware, this value is retained by the device as a pellet send location.  If it was requested in
        # UI or from a configuration file prior to connection, having called set_(x/y/z) at some point will have not had
        # any effect on the hardware.
        self.set_x(self.x)
        self.set_y(self.y)
        self.set_z(self.z)

        self._is_connected = True

    def disconnect_from_device(self):
        if not self._is_connected:
            return

        self._send_command(DeviceThreadMessageKind.TERMINATE)

        self._is_connected = False

    def on_activated(self):
        self._message_handler.start()

    def on_close(self):
        self.disconnect_from_device()
        self._message_queue.put((DeviceThreadMessageKind.TERMINATE, None))

    def load_configuration(self, configuration: dict):
        if "port" in configuration:
            self.port = configuration["port"]
        if "x" in configuration:
            self.set_x(configuration["x"])
        if "y" in configuration:
            self.set_y(configuration["y"])
        if "z" in configuration:
            self.set_z(configuration["z"])

    def save_configuration(self) -> dict:
        return {"port": self.port, "x": self._x, "y": self._y, "z": self._z}

    def _send_with_token(self, cmd, data=None):
        token = uuid.uuid4()

        if self._send_command(cmd, data, token):
            return token
        else:
            return None

    def _send_command(self, message, data=None, context=None) -> bool:
        if self._device_thread is not None:
            self._device_thread.send_message(message, data, context)
            return True

        return False
