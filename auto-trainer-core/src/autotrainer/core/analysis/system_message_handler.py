import logging
from queue import Queue
from typing import Callable

from autotrainer.core import SystemStatusMessageKind

from .message_handler import MessageHandler
from .sensor_analysis import SensorAnalysis

logger = logging.getLogger(__name__)


class SystemMessageHandler(MessageHandler):
    def __init__(self, input_queue: Queue):
        super().__init__(input_queue, name="system-message-handler")

        self._measurement_callback = None

        self._analysis = SensorAnalysis()

    @property
    def measurement_callback(self):
        return self._measurement_callback

    @measurement_callback.setter
    def measurement_callback(self, measurement_callback: Callable[[tuple], None]) -> None:
        self._measurement_callback = measurement_callback

    @property
    def analysis(self):
        return self._analysis

    def message_received(self, msg, data):
        if msg == SystemStatusMessageKind.PELLET_X:
            self.property_changed("device_x", data, None)
        elif msg == SystemStatusMessageKind.PELLET_Y:
            self.property_changed("device_y", data, None)
        elif msg == SystemStatusMessageKind.PELLET_Z:
            self.property_changed("device_z", data, None)
        elif msg == SystemStatusMessageKind.PELLET_LOAD:
            self.property_changed("load_angle", data, None)
        elif msg == SystemStatusMessageKind.PELLET_COVER:
            self.property_changed("cover_angle", data, None)
        elif msg == SystemStatusMessageKind.STREAM_START:
            self._analysis.stream_start()
        elif msg == SystemStatusMessageKind.HEAD_MAGNET:
            pass
        elif msg == SystemStatusMessageKind.MEASUREMENT or msg == SystemStatusMessageKind.MEASUREMENTS:
            weights, switch, pressure, temperature, humidity = self._analysis.measurements_received(data)

            # Measurement callback.
            if self._measurement_callback is not None:
                self._measurement_callback((weights, switch, pressure, temperature, humidity))
