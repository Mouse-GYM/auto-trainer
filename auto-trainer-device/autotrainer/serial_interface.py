import sys

import serial
import serial.tools.list_ports

from . device_interface import IDeviceInterface


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

    def open(self):
        self._serial = serial.Serial(self._port)

    def close(self):
        self._serial.close()

    def can_read(self) -> bool:
        return self._serial.in_waiting > 0

    def read(self) -> bytes:
        return self._serial.read(1)

    def write(self, value: bytes) -> int:
        return self._serial.write(value)

    def write_str(self, value: str) -> int:
        return self._serial.write(value.encode())
