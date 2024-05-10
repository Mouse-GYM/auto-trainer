import logging
import queue
import uuid

from PySide6.QtCore import QThread
from autotrainer.serial_interface import SerialInterface
from autotrainer.pellet_delivery import PelletDelivery, PelletDeliveryMessageKind
from autotrainer.device_thread import DeviceThread, DeviceThreadMessageKind
from autotrainer.pellet_reader import PelletReader

from tools.acquisition.model.user_settings import UserSettings

logger = logging.getLogger(__name__)


class PelletDeliveryModel:
    def __init__(self, user_settings: UserSettings):
        self._user_settings = user_settings

        self._cmd_queue = queue.Queue()
        self._msg_queue = queue.Queue()
        self._device_thread = None

        self._measurement_thread = QThread()
        self._pellet_reader = PelletReader(self._msg_queue)
        self._pellet_reader.moveToThread(self._measurement_thread)
        self._measurement_thread.started.connect(self._pellet_reader.process)

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

    @property
    def pellet_reader(self):
        return self._pellet_reader

    def refresh_ports(self):
        self._ports = SerialInterface.list_ports()

    def send_home(self) -> object:
        token = uuid.uuid4()
        self._send_command(PelletDeliveryMessageKind.SEND_HOME, None, token)
        return token

    def load_pellet(self) -> object:
        token = uuid.uuid4()
        self._send_command(PelletDeliveryMessageKind.LOAD_PELLET, None, token)
        return token

    def send_pellet(self) -> object:
        token = uuid.uuid4()
        self._send_command(PelletDeliveryMessageKind.SEND_PELLET, None, token)
        return token

    def release_pellet(self) -> object:
        token = uuid.uuid4()
        self._send_command(PelletDeliveryMessageKind.RELEASE_PELLET, None, token)
        return token

    def set_x(self, value: int) -> object:
        token = uuid.uuid4()
        self._send_command(PelletDeliveryMessageKind.SET_X, value, token)
        return token

    def set_y(self, value: int) -> object:
        token = uuid.uuid4()
        self._send_command(PelletDeliveryMessageKind.SET_Y, value, token)
        return token

    def set_z(self, value: int) -> object:
        token = uuid.uuid4()
        self._send_command(PelletDeliveryMessageKind.SET_Z, value, token)
        return token

    def connect_to_device(self):
        if len(self.port) == 0:
            return

        with self._cmd_queue.mutex:
            self._cmd_queue.queue.clear()

        device_interface = SerialInterface(self.port)

        pellet_delivery = PelletDelivery(device_interface)

        self._device_thread = DeviceThread(pellet_delivery, device_interface, self._cmd_queue, self._msg_queue)

        self._device_thread.start()

        self._measurement_thread.start()

        self._is_connected = True

    def disconnect_from_device(self):
        if not self._is_connected:
            return

        self._send_command(DeviceThreadMessageKind.TERMINATE)

        self._is_connected = False

    def on_close(self):
        self.disconnect_from_device()
        self._msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))
        self._send_command(DeviceThreadMessageKind.TERMINATE)

    def _send_command(self, message, data=None, context=None):
        self._cmd_queue.put((message, data, context))
