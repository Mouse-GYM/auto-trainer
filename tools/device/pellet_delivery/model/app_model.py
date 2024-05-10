import logging
import queue
import uuid

from PySide6.QtCore import QThread

from autotrainer.serial_interface import SerialInterface
from autotrainer.pellet_delivery import PelletDelivery, PelletDeliveryMessageKind
from autotrainer.device_thread import DeviceThread, DeviceThreadMessageKind
from autotrainer.pellet_reader import PelletReader

from tools.device.pellet_delivery.model.user_settings import UserSettings

logger = logging.getLogger(__name__)


class AppModel:
    def __init__(self):
        self._user_settings = UserSettings()

        self._cmd_queue = queue.Queue()
        self._msg_queue = queue.Queue()
        self._device_thread = None

        self._measurement_thread = QThread()
        self._measurement_worker = PelletReader(self._msg_queue)
        self._measurement_worker.moveToThread(self._measurement_thread)
        self._measurement_thread.started.connect(self._measurement_worker.process)

        self._is_connected = False

        self._command_token = None

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
    def reader(self) -> PelletReader:
        return self._measurement_worker

    def refresh_ports(self):
        self._ports = SerialInterface.list_ports()

    def send_home(self):
        self._command_token = uuid.uuid4()
        logger.debug(f"sending home with token {self._command_token}")
        self._send_command(PelletDeliveryMessageKind.SEND_HOME, None, self._command_token)

    def load_pellet(self):
        self._send_command(PelletDeliveryMessageKind.LOAD_PELLET)

    def send_pellet(self):
        self._send_command(PelletDeliveryMessageKind.SEND_PELLET)

    def release_pellet(self):
        self._send_command(PelletDeliveryMessageKind.RELEASE_PELLET)

    def set_x(self, value: int):
        self._send_command(PelletDeliveryMessageKind.SET_X, value)

    def set_y(self, value: int):
        self._send_command(PelletDeliveryMessageKind.SET_Y, value)

    def set_z(self, value: int):
        self._send_command(PelletDeliveryMessageKind.SET_Z, value)

    def connect_to_device(self):
        device_interface = SerialInterface(self._user_settings.port)

        pellet_delivery = PelletDelivery(device_interface)

        self._device_thread = DeviceThread(pellet_delivery, device_interface, self._cmd_queue, self._msg_queue)

        self._device_thread.start()

        self._measurement_thread.start()

        self._is_connected = True

    def disconnect_from_device(self):
        self._send_command(DeviceThreadMessageKind.TERMINATE)

        self._is_connected = False

    def on_close(self):
        self.disconnect_from_device()
        self._send_command(DeviceThreadMessageKind.TERMINATE)

    def _send_command(self, message, data=None, context=None):
        self._cmd_queue.put((message, data, context))
