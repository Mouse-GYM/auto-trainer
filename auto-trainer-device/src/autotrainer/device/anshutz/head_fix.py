import logging
import time
import re
import typing
from threading import Timer

from autotrainer.core import PerfMonitor, SystemCommandKind, SystemStatusMessageKind

from ..device_api import DeviceApi
from autotrainer.core.analysis.head_fix_measurement import HeadFixMeasurement

from .serial_interface import SerialInterface
from .gym_device import GymDevice

logger = logging.getLogger(__name__)


class HeadFix(GymDevice):
    def __init__(self, port: str, api: DeviceApi = None, buffer_size: int = 50):
        super().__init__(SerialInterface(port), api)

        self._identifier = "H"

        # This hardware does not support status messages for servo, stepper, or DIO.  For commands that may change these
        # values, store the expected value, assumes it was successful, and send a status message after it completes and
        # has been acknowledged.  This allows scripts/apps to see the updates they would expect from the new hardware.
        self._commands_with_status = {}

        self._measurement_buffer_count = buffer_size

        self._measurements = list()

        self._perf_monitor = PerfMonitor(name="<head-fix>", units="mps", report_window=30)

    @property
    def measurements(self) -> typing.List[HeadFixMeasurement]:
        return self._measurements

    @property
    def buffer_size(self) -> int:
        return self._measurement_buffer_count

    def connect(self):
        # Force streaming to stop if active.
        self._send_data("Tx")

    def notify_message(self, kind: int, data: object, context: object = None):
        if kind == SystemCommandKind.RAW_COMMAND:
            self._send_data(typing.cast(str, data), context)
        elif kind == SystemCommandKind.REQUEST_VERSION:
            self._send_data("Fx", context)
        elif kind == SystemCommandKind.MOVE_MAGNET_SERVO:
            if isinstance(data, float):
                val = int(data)
            else:
                val = typing.cast(int, data)
            self._send_data(f"A{val}x", context)
            if context is not None:
                self._commands_with_status[context] = (SystemCommandKind.MOVE_MAGNET_SERVO, val)
            self.api.send_message(SystemStatusMessageKind.HEAD_MAGNET, val)
        elif kind == SystemCommandKind.MOVE_GATE_SERVO:
            if isinstance(data, float):
                val = int(data)
            else:
                val = typing.cast(int, data)
            self._send_data(f"A{val}x", context)
            if context is not None:
                self._commands_with_status[context] = (SystemCommandKind.MOVE_GATE_SERVO, val)
            self.api.send_message(SystemStatusMessageKind.TUNNEL_GATE_SERVO, val)
        elif kind == SystemCommandKind.SETTINGS:
            self._send_data("Ox", context)
        elif kind == SystemCommandKind.UPDATE_SCALE_TARE:
            self._send_data("Mx", context)
        elif kind == SystemCommandKind.STREAM_START:
            self._perf_monitor.reset()
            self._send_data("Sx", context)
        elif kind == SystemCommandKind.STREAM_STOP:
            self._send_data("Tx", context)
        elif kind == SystemCommandKind.OPEN_TUNNEL_GATE:
            if context is not None:
                Timer(0.5, lambda: self._acknowledge_command(context)).start()
        elif kind == SystemCommandKind.CLOSE_TUNNEL_GATE:
            if context is not None:
                Timer(0.5, lambda: self._acknowledge_command(context)).start()
        elif kind == SystemCommandKind.SET_SEND_PELLET_PROCEDURE or \
            kind == SystemCommandKind.SET_LOAD_PELLET_PROCEDURE or \
            kind == SystemCommandKind.SET_COVER_PELLET_PROCEDURE or \
            kind == SystemCommandKind.SET_RELEASE_PELLET_PROCEDURE or \
            kind == SystemCommandKind.WRITE_MOTOR_CONFIGURATION:
            pass
        else:
            logger.warning(f"unknown message kind: {kind}")

    def _acknowledge_command(self, token: object):
        response = self._commands_with_status.pop(token, None)

        super()._acknowledge_command(token)

        if response is not None:
            if response[0] == SystemCommandKind.MOVE_MAGNET_SERVO:
                self.api.send_message(SystemStatusMessageKind.HEAD_MAGNET, response[1])
            elif response[0] == SystemCommandKind.MOVE_GATE_SERVO:
                self.api.send_message(SystemStatusMessageKind.TUNNEL_GATE_SERVO, response[1])

    def insert_measurements(self, data: str) -> str:
        return self._handle_response("", data)

    def _handle_response(self, cmd: str, data: str) -> str:
        residual = super()._handle_response(cmd, data)

        if len(residual) > 0:
            measurements, residual = parse_measurements(residual)

            for measurement in measurements:
                self._measurements.append(measurement)

                if len(self._measurements) >= self._measurement_buffer_count:
                    self._api.send_message(SystemStatusMessageKind.MEASUREMENT,
                                           self._measurements.copy())
                    self._measurements = list()

            self._perf_monitor.add_cycles(len(measurements))

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
            measurement = HeadFixMeasurement(time.time(), time.perf_counter_ns(),
                                             int(parts[0]) / 10.0, int(parts[1]),
                                             int(parts[2]), int(parts[3]) / 10.0,
                                             int(parts[4]) / 10.0)

            if len(parts) > 5:
                print(len(parts))
                print(parts[5])
                return measurement, parts[5]
            else:
                return measurement, ""
        except Exception as ex:
            logger.warning(f"unexpected pattern: {data}")
            logger.warning(ex)

    return None, data
