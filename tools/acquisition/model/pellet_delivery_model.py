import logging
import uuid
from typing import Optional

from autotrainer.core import ObservableObject, ProjectInfo, SystemCommandKind
from autotrainer.device import get_available_hardware, DeviceConnectionProtocol
from autotrainer.model import EnvironmentProvider

logger = logging.getLogger(__name__)


class PelletDeliveryModel(ObservableObject):
    def __init__(self):
        super().__init__()

        self._device = None

        self._port = None

        self._is_connected = False

        self._x = 0

        self._y = 0

        self._z = 0

        self._project: Optional[ProjectInfo] = None

    @property
    def device(self) -> Optional[DeviceConnectionProtocol]:
        return self._device

    @device.setter
    def device(self, value: Optional[DeviceConnectionProtocol]) -> None:
        self._device = value

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

    def play_tone(self, frequency: int, _duration: float) -> object:
        return self._send_with_token(SystemCommandKind.PLAY_TONE, frequency)

    def refresh_ports(self):
        return get_available_hardware(allow_can_emulation=EnvironmentProvider.allow_can_emulation())

    def on_connect(self, device: DeviceConnectionProtocol):
        self._device = device

        self.set_x(self.x)
        self.set_y(self.y)
        self.set_z(self.z)

        self._is_connected = True

    def on_disconnect(self):
        self._device = None
        self._is_connected = False

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
        if self._device is not None:
            self._device.send_message(message, data, context)
            return True

        return False
