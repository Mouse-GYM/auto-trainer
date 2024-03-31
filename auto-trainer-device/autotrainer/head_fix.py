import logging
import re
import typing
from collections import namedtuple
from enum import IntEnum

from .device_api import DeviceApi
from .device_listener import IDeviceListener

logger = logging.getLogger(__name__)

HeadFixMeasurement = namedtuple('HeadFixMeasurement', ["weight", "switch", "pressure"])


class HeadFixMessageKind(IntEnum):
    MEASUREMENT = 1,
    SERVO = 2,
    SETTINGS = 3


def handle_info(buffer: str):
    logger.info(buffer)


class HeadFix(IDeviceListener):
    def __init__(self, api: DeviceApi = None):
        self._api = api

        self._buffer = ""

        self._measurement_buffer_count = 10

        self._measurements = list()

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        self._api = value

    def connect(self):
        pass

    def disconnect(self):
        pass

    def notify_data(self, data: bytes):
        self._buffer += data.decode()

        if self._buffer[-1] == "n":
            self.handle_data(self._buffer)
            self._buffer = ""
        elif self._buffer[-1] == "\n":
            handle_info(self._buffer)
            self._buffer = ""

    def notify_message(self, kind: int, context: object):
        self._api.send_data_str(typing.cast(str, context))

    def handle_data(self, buffer: str):
        if buffer[0] == "s":
            parts = re.split(r"[d a]", buffer[1:-1])

            if len(parts) == 3:
                try:
                    measurement = HeadFixMeasurement(int(parts[0]), int(parts[1]), int(parts[2]))

                    self._measurements.append(measurement)

                    if len(self._measurements) >= self._measurement_buffer_count:
                        self._api.send_message(HeadFixMessageKind.MEASUREMENT, self._measurements.copy())
                        self._measurements = list()
                except:
                    logger.warning(f"unexpected pattern: {buffer}")
