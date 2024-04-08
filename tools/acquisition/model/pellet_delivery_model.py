import logging
import queue

from autotrainer.serial_interface import SerialInterface
from autotrainer.pellet_delivery import PelletDelivery, PelletDeliveryMessageKind
from autotrainer.device_thread import DeviceThread, DeviceThreadMessageKind

from tools.acquisition.model.user_settings import UserSettings

logger = logging.getLogger(__name__)


class PelletDeliveryModel:
    def __init__(self, user_settings: UserSettings):
        self._user_settings = user_settings

        self._cmd_queue = queue.Queue()
        self._msg_queue = queue.Queue()
        self._device_thread = None

        self._is_connected = False

        self._ports = list()

        self.refresh_ports()

    @property
    def ports(self):
        return self._ports

    @property
    def port(self) -> str:
        return self._user_settings.pellet_port

    @port.setter
    def port(self, port: str):
        self._user_settings.pellet_port = port

    @property
    def is_connected(self):
        return self._is_connected

    def refresh_ports(self):
        self._ports = SerialInterface.list_ports()

    def send_home(self):
        self._cmd_queue.put((PelletDeliveryMessageKind.SEND_HOME, ""))

    def load_pellet(self):
        self._cmd_queue.put((PelletDeliveryMessageKind.LOAD_PELLET, ""))

    def send_pellet(self):
        self._cmd_queue.put((PelletDeliveryMessageKind.SEND_PELLET, ""))

    def release_pellet(self):
        self._cmd_queue.put((PelletDeliveryMessageKind.RELEASE_PELLET, ""))

    def set_x(self, value: int):
        self._cmd_queue.put((PelletDeliveryMessageKind.SET_X, value))

    def set_y(self, value: int):
        self._cmd_queue.put((PelletDeliveryMessageKind.SET_Y, value))

    def set_z(self, value: int):
        self._cmd_queue.put((PelletDeliveryMessageKind.SET_Z, value))

    def connect_to_device(self):
        if len(self.port) == 0:
            return

        with self._cmd_queue.mutex:
            self._cmd_queue.queue.clear()

        device_interface = SerialInterface(self.port)

        pellet_delivery = PelletDelivery(device_interface)

        self._device_thread = DeviceThread(pellet_delivery, device_interface, self._cmd_queue, self._msg_queue)

        self._device_thread.start()

        self._is_connected = True

    def disconnect_from_device(self):
        if not self._is_connected:
            return

        self._cmd_queue.put((DeviceThreadMessageKind.TERMINATE, None))

        self._is_connected = False

    def on_close(self):
        self.disconnect_from_device()
        self._msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))
