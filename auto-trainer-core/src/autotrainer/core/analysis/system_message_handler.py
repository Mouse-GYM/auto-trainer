import logging
from queue import Queue
from typing import Callable, List

from ..message import SystemStatusMessageKind

from .message_handler import MessageHandler
from .sensor_analysis import SensorAnalysis

logger = logging.getLogger(__name__)


class SystemMessageHandler(MessageHandler):
    def __init__(self, input_queue: Queue):
        super().__init__(input_queue, name="system-message-handler")

        self._measurement_callback = None
        self._audio_callback = None

        self._analysis = SensorAnalysis()

    @property
    def measurement_callback(self):
        return self._measurement_callback

    @measurement_callback.setter
    def measurement_callback(self, measurement_callback: Callable[[tuple], None]) -> None:
        self._measurement_callback = measurement_callback

    @property
    def audio_callback(self):
        return self._audio_callback

    @audio_callback.setter
    def audio_callback(self, audio_callback: Callable[[List[float]], None]) -> None:
        self._audio_callback = audio_callback

    @property
    def analysis(self):
        return self._analysis

    def message_received(self, msg, data):
        # TODO: some simulated property changes events for the next ~6 messages to enable feedback in callers.  If this
        # turns out to be the desired behavior, it should probably be formalized a bit better.
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
        elif msg == SystemStatusMessageKind.HEAD_MAGNET:
            self.property_changed("head_magnet_intensity", data, None)
        elif msg == SystemStatusMessageKind.AUDIO_SPECTRUM:
            self._analysis.audio_spectrum_received(data)
            if self._audio_callback is not None:
                self._audio_callback(data.magnitudes)
        elif msg == SystemStatusMessageKind.MEASUREMENT or msg == SystemStatusMessageKind.MEASUREMENTS:
            weights, switch, pressure, temperature, humidity = self._analysis.measurements_received(
                data)

            if self._measurement_callback is not None:
                self._measurement_callback((weights, switch, pressure, temperature, humidity))
        elif msg == SystemStatusMessageKind.FRONT_DOOR:
            self.property_changed("front_door", data, None)
        elif msg == SystemStatusMessageKind.DRAWER_DOOR:
            self.property_changed("drawer_door", data, None)
        elif msg == SystemStatusMessageKind.STIMULUS_INPUTS:
            self._on_property_changed("stimuli", data, None)
        elif msg == SystemStatusMessageKind.MOTOR_CONFIGURATION:
            self._on_property_changed("config", data, None)
