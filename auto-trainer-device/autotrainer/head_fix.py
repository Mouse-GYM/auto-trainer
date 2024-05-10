import logging
import time
import re
import typing
from collections import namedtuple
from enum import IntEnum

from .device_api import DeviceApi
from .device_listener import IDeviceListener

logger = logging.getLogger(__name__)

HeadFixMeasurement = namedtuple('HeadFixMeasurement', ["weight", "switch", "pressure", "temperature", "humidity"])


class HeadFixMessageKind(IntEnum):
    RAW_COMMAND = 1,
    MEASUREMENT = 2,
    SERVO = 3,
    SETTINGS = 4,
    VERSION = 5,
    UPDATE_TARE = 6


class HeadFix(IDeviceListener):
    def __init__(self, api: DeviceApi = None, buffer_size: int = 50):
        self._api = api

        self._buffer = ""

        self._measurement_buffer_count = buffer_size

        self._measurements = list()

        self._firmware_version = ""

        self._measurement_count = 0
        self._start = None

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        self._api = value

    @property
    def firmware_version(self):
        return self._firmware_version

    def connect(self):
        self._api.send_data_str("Fx")
        self._start = time.perf_counter_ns()
        self._measurement_count = 0

    def disconnect(self):
        pass

    def notify_data(self, data: bytes):
        try:
            self._buffer += data.decode()

            parts = self._buffer.split("\n")
            if len(parts) > 1:
                for idx in range(len(parts) - 1):
                    self._handle_info(parts[idx])
                self._buffer = parts[len(parts) - 1]

            parts = self._buffer.split("n")
            if len(parts) > 1:
                for idx in range(len(parts) - 1):
                    self._handle_data(parts[idx])
                self._buffer = parts[len(parts) - 1]
            '''
            if self._buffer[-1] == "n":
                self._handle_data(self._buffer)
                self._buffer = ""
            elif self._buffer[-1] == "\n":
                self._handle_info(self._buffer)
                self._buffer = ""
            '''
        except Exception as ex:
            logger.error(ex)

    def notify_message(self, kind: int, data: object, context: object):
        if kind == HeadFixMessageKind.RAW_COMMAND:
            self._api.send_data_str(typing.cast(str, data))
        elif kind == HeadFixMessageKind.VERSION:
            self._api.send_data_str("Fx")
        elif kind == HeadFixMessageKind.SERVO:
            self._api.send_data_str(f"A{typing.cast(str, data)}x")
        elif kind == HeadFixMessageKind.SETTINGS:
            self._api.send_data_str("Ox")
        elif kind == HeadFixMessageKind.UPDATE_TARE:
            self._api.send_data_str("Mx")
        else:
            logger.warning(f"unknown message kind: {kind}")

    def _set_firmware_version(self, value: str):
        self._firmware_version = value
        self._api.send_message(HeadFixMessageKind.VERSION, self._firmware_version)

    def _handle_info(self, buffer: str):
        if buffer[0] == "F":
            if len(buffer) > 2:
                if buffer[1] == "H":
                    self._set_firmware_version(buffer[2:])
                else:
                    self._set_firmware_version("unknown device")
            else:
                self._set_firmware_version("unknown device id response")

        logger.info(buffer)

    def _handle_data(self, buffer: str):
        if len(buffer) == 0:
            return

        if buffer[0] == "s":
            parts = re.split(r"[d a t h]", buffer[1:])

            if len(parts) > 2:
                try:
                    if len(parts) == 3:
                        measurement = HeadFixMeasurement(int(parts[0]), int(parts[1]), int(parts[2]), 0.0, 0.0)
                    else:
                        measurement = HeadFixMeasurement(int(parts[0])/10.0, int(parts[1]), int(parts[2]),
                                                         int(parts[3])/10.0, int(parts[4])/10.0)

                    self._measurements.append(measurement)

                    self._measurement_count += 1

                    if self._measurement_count % 1000 == 0:
                        logger.info(f"<head fix>{(1e9 * self._measurement_count/ (time.perf_counter_ns() - self._start)):.1f} mps")

                    if len(self._measurements) >= self._measurement_buffer_count:
                        self._api.send_message(HeadFixMessageKind.MEASUREMENT, self._measurements.copy())
                        self._measurements = list()
                except:
                    logger.warning(f"unexpected pattern: {buffer}")
