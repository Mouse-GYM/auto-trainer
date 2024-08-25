import logging
import math
import sys

import serial
import serial.tools.list_ports

from .device_interface import DeviceInterface

logger = logging.getLogger(__name__)


def windows_port_sort_key(port: str):
    if port.startswith("COM"):
        return int(port[3:])

    return str


class SerialInterface(DeviceInterface):
    _all_ports: list = list()

    _manual_ports: list = list()

    @classmethod
    def get_ports(cls) -> list:
        return cls._all_ports

    @classmethod
    def include_port(cls, port: str):
        if port not in cls._manual_ports:
            cls._manual_ports.append(port)
            cls._all_ports.append(port)
            cls._manual_ports.sort()

    @classmethod
    def refresh_ports(cls) -> list:
        ports = list()

        for port in serial.tools.list_ports.comports():
            ports.append(port.device)

        for port in cls._manual_ports:
            ports.append(port)

        sort_key = windows_port_sort_key if sys.platform == "win32" else None

        ports.sort(key=sort_key)

        cls._all_ports = ports

        return cls._all_ports

    def __init__(self, port: str, baudrate: int = 115200):
        super().__init__()
        self._port = port
        self._serial = None
        self._baudrate = baudrate

    @property
    def baudrate(self) -> int:
        return self._baudrate

    @baudrate.setter
    def baudrate(self, value: int):
        if self.is_open:
            raise RuntimeError("Cannot set baudrate when the device is already open")

        self._baudrate = value

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def open(self) -> bool:
        try:
            self._serial = serial.Serial(self._port, self._baudrate)
        except Exception as e:
            if "FileNotFoundError" not in f"{e}":
                logger.exception(e)
            else:
                logger.error(f"{self._port} is not available")

        return self.is_open

    def close(self):
        if self.is_open:
            self._serial.close()
            self._serial = None

    def can_read(self) -> bool:
        return self.is_open and self._serial.in_waiting > 0

    def read(self, max_count: int = math.inf) -> bytes:
        if self.can_read():
            return self._serial.read(min(self._serial.in_waiting, max_count))

        return b""

    def write(self, value: bytes) -> int:
        if self.is_open:
            return self._serial.write(value)

        return 0

    def write_str(self, value: str) -> int:
        if self.is_open:
            return self._serial.write(value.encode())

        return 0
