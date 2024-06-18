import logging
import time
import re
import typing
from collections import namedtuple
from enum import IntEnum

from .gym_device import GymDevice, GymDeviceMessageKind
from .device_api import DeviceApi

logger = logging.getLogger(__name__)

HeadFixMeasurement = namedtuple('HeadFixMeasurement', ["weight", "switch", "pressure", "temperature", "humidity"])


class HeadFixMessageKind(IntEnum):
    RAW_COMMAND = 1,
    MEASUREMENT = 2,
    SERVO = 3,
    SETTINGS = 4,
    UPDATE_TARE = 5,
    STREAM_START = 6,
    STREAM_STOP = 7


class HeadFix(GymDevice):
    def __init__(self, api: DeviceApi = None, buffer_size: int = 50):
        super().__init__(api)

        self._identifier = "H"

        self._measurement_buffer_count = buffer_size

        self._measurements = list()

        self._measurement_count = 0
        self._start = None

    @property
    def measurements(self) -> typing.List[HeadFixMeasurement]:
        return self._measurements

    def connect(self):
        # Force streaming to stop if active.
        self._send_data("Tx")

    def notify_message(self, kind: int, data: object, context: object = None):
        if kind == HeadFixMessageKind.RAW_COMMAND:
            self._send_data(typing.cast(str, data), context)
        elif kind == GymDeviceMessageKind.VERSION:
            self._send_data("Fx", context)
        elif kind == HeadFixMessageKind.SERVO:
            self._send_data(f"A{typing.cast(str, data)}x", context)
        elif kind == HeadFixMessageKind.SETTINGS:
            self._send_data("Ox", context)
        elif kind == HeadFixMessageKind.UPDATE_TARE:
            self._send_data("Mx", context)
        elif kind == HeadFixMessageKind.STREAM_START:
            self._measurement_count = 0
            self._send_data("Sx", context)
            self._start = time.perf_counter_ns()
        elif kind == HeadFixMessageKind.STREAM_STOP:
            self._send_data("Tx", context)
        else:
            logger.warning(f"unknown message kind: {kind}")

    def insert_measurements(self, data: str) -> str:
        return self._handle_response("", data)

    def _handle_response(self, cmd: str, data: str) -> str:
        residual = super()._handle_response(cmd, data)

        if len(residual) > 0:
            measurements, residual = parse_measurements(residual)

            for measurement in measurements:
                self._measurements.append(measurement)

                self._measurement_count += 1

                if self._measurement_count % 1000 == 0:
                    logger.info(
                        f"{(1e9 * self._measurement_count / (time.perf_counter_ns() - self._start)):.1f} mps")

                if len(self._measurements) >= self._measurement_buffer_count:
                    self._api.send_message(HeadFixMessageKind.MEASUREMENT, self._measurements.copy())
                    self._measurements = list()

            # Don't let unhandled/expected data overflow the read buffer.
            if len(residual) > 1000:
                logger.warning("clearing buffer")
                residual = ""

        return residual


def parse_measurements(data: str) -> (list, str):
    measurements = list()

    residual = ""

    lines = data.splitlines()

    for line in lines:
        buffers = line.split("n")

        for buffer in buffers:
            measurement, res = parse_measurement(buffer)

            if measurement is not None:
                measurements.append(measurement)

            residual += res

    return measurements, residual


def parse_measurement(data: str) -> (HeadFixMeasurement, str):
    if len(data) == 0:
        return None, ""

    if data[0] == "s":
        parts = re.split(r"[d a t h n]", data[1:].strip())

        if len(parts) < 5:
            return None, data

        try:
            measurement = HeadFixMeasurement(int(parts[0]) / 10.0, int(parts[1]), int(parts[2]),
                                             int(parts[3]) / 10.0, int(parts[4]) / 10.0)

            if len(parts) > 5:
                print(len(parts))
                print(parts[5])
                return measurement, parts[5]
            else:
                return measurement, ""
        except:
            logger.warning(f"unexpected pattern: {data}")

    return None, data
