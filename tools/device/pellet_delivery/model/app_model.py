import queue
import sys

import serial.tools.list_ports

from autotrainer.serial_interface import SerialInterface
from autotrainer.pellet_delivery import PelletDelivery, PelletDeliveryMessageKind
from autotrainer.device_thread import DeviceThread, DeviceThreadMessageKind

from tools.device.pellet_delivery.model.user_settings import UserSettings


class AppModel:
    def __init__(self):
        self._user_settings = UserSettings()

        self._cmd_queue = queue.Queue()
        self._msg_queue = queue.Queue()
        self._device_thread = None

        self._is_connected = False

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

    def refresh_ports(self):
        self._ports = list()

        for port in serial.tools.list_ports.comports():
            self._ports.append(port.device)

        if sys.platform.startswith("linux"):
            self._ports.append("/dev/ttyTHS0")

        self._ports.sort()

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
        device_interface = SerialInterface(self._user_settings.port)

        pellet_delivery = PelletDelivery(device_interface)

        self._device_thread = DeviceThread(pellet_delivery, device_interface, self._cmd_queue, self._msg_queue)

        self._device_thread.start()

        self._is_connected = True

    def disconnect_from_device(self):
        self._cmd_queue.put((DeviceThreadMessageKind.TERMINATE, None))
        self._msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))

        self._is_connected = False

    def on_close(self):
        self.disconnect_from_device()
