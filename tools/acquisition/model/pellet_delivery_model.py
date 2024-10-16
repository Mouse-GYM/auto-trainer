import logging
import queue
import uuid

from autotrainer.core import ObservableObject
from autotrainer.device import SerialInterface
from autotrainer.device import PelletDelivery, PelletDeliveryMessageKind
from autotrainer.device import DeviceThread, DeviceThreadMessageKind
from autotrainer.device import PelletReader

logger = logging.getLogger(__name__)


class PelletDeliveryModel(ObservableObject):
    def __init__(self):
        super().__init__()

        self._message_queue = queue.Queue()

        self._port = None

        self._device_thread = None

        self._pellet_reader = None
        self._pellet_reader = PelletReader(self._message_queue)

        self._is_connected = False

        self._x = 0

        self._y = 0

        self._z = 0

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
    def pellet_reader(self) -> PelletReader:
        return self._pellet_reader

    def set_x(self, value: int) -> object:
        self._x = self._on_property_changed("x", value, self._x)

        return self._send_with_token(PelletDeliveryMessageKind.SET_X, value)

    def set_y(self, value: int) -> object:
        self._y = self._on_property_changed("y", value, self._y)

        return self._send_with_token(PelletDeliveryMessageKind.SET_Y, value)

    def set_z(self, value: int) -> object:
        self._z = self._on_property_changed("z", value, self._z)

        return self._send_with_token(PelletDeliveryMessageKind.SET_Z, value)

    def send_home(self) -> object:
        return self._send_with_token(PelletDeliveryMessageKind.SEND_HOME)

    def load_pellet(self) -> object:
        return self._send_with_token(PelletDeliveryMessageKind.LOAD_PELLET)

    def send_pellet(self) -> object:
        return self._send_with_token(PelletDeliveryMessageKind.SEND_PELLET)

    def release_pellet(self) -> object:
        return self._send_with_token(PelletDeliveryMessageKind.RELEASE_PELLET)

    def cover_pellet(self) -> object:
        return self._send_with_token(PelletDeliveryMessageKind.COVER_PELLET)

    def connect_to_device(self):
        if not self.port or len(self.port) == 0:
            return

        device_interface = SerialInterface(self.port)

        pellet_delivery = PelletDelivery()

        self._device_thread = DeviceThread(pellet_delivery, device_interface, self._message_queue)
        self._device_thread.name = "pellet"

        self._device_thread.start()

        self._device_thread.send_message(DeviceThreadMessageKind.CONNECT)

        self._is_connected = True

    def disconnect_from_device(self):
        if not self._is_connected:
            return

        self._send_command(DeviceThreadMessageKind.TERMINATE)

        self._is_connected = False

    def on_activated(self):
        self._pellet_reader.start()

    def on_close(self):
        self.disconnect_from_device()
        self._message_queue.put((DeviceThreadMessageKind.TERMINATE, None))

    def load_configuration(self, conf):
        if "port" in conf:
            self.port = conf["port"]
        if "x" in conf:
            self.set_x(conf["x"])
        if "y" in conf:
            self.set_y(conf["y"])
        if "z" in conf:
            self.set_z(conf["z"])

    def write_configuration(self):
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
