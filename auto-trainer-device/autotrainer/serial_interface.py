import sys

import serial
import serial.tools.list_ports

from .device_interface import IDeviceInterface


class SerialInterface(IDeviceInterface):
    @classmethod
    def list_ports(cls) -> list:
        ports = list()

        for port in serial.tools.list_ports.comports():
            ports.append(port.device)

        if sys.platform.startswith("linux"):
            ports.append("/dev/ttyTHS0")

        ports.sort()

        return ports

    def __init__(self, port: str):
        super().__init__()
        self._port = port
        self._serial = None
        self._is_open = False

    def open(self):
        try:
            self._serial = serial.Serial(self._port, baudrate=115200)
            self._is_open = True
        except:
            self._is_open = False

    def close(self):
        if self._is_open:
            self._serial.close()

    def can_read(self) -> bool:
        return self._is_open and self._serial.in_waiting > 0

    def read(self) -> bytes:
        if self._is_open:
            return self._serial.read(1)

    def write(self, value: bytes) -> int:
        if self._is_open:
            return self._serial.write(value)

        return 0

    def write_str(self, value: str) -> int:
        if self._is_open:
            return self._serial.write(value.encode())

        return 0
