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
        # TODO: These are treated as if the property has changed.  If the number of event listeners increases or their
        #  behaviors are complex and do not check for change themselves, this could become a bottleneck.  This could be
        #  updated to store previous values and only notify listeners on change, like a typical ObservableObject
        #  implementation.  Keeping things simple for the time being.
        if msg == SystemStatusMessageKind.PELLET_X:
            self.property_changed(MessageHandler.DEVICE_X_PROPERTY, data, None)
        elif msg == SystemStatusMessageKind.PELLET_Y:
            self.property_changed(MessageHandler.DEVICE_Y_PROPERTY, data, None)
        elif msg == SystemStatusMessageKind.PELLET_Z:
            self.property_changed(MessageHandler.DEVICE_Z_PROPERTY, data, None)
        elif msg == SystemStatusMessageKind.PELLET_LOAD:
            self.property_changed(MessageHandler.LOAD_ARM_ANGLE_PROPERTY, data, None)
        elif msg == SystemStatusMessageKind.PELLET_COVER:
            self.property_changed(MessageHandler.COVER_ARM_ANGLE_PROPERTY, data, None)
        elif msg == SystemStatusMessageKind.HEAD_MAGNET:
            self.property_changed(MessageHandler.HEAD_MAGNET_INTENSITY_PROPERTY, data, None)
        elif msg == SystemStatusMessageKind.FRONT_DOOR:
            self.property_changed(MessageHandler.FRONT_DOOR_PROPERTY, data, None)
        elif msg == SystemStatusMessageKind.DRAWER_DOOR:
            self.property_changed(MessageHandler.DRAWER_DOOR_PROPERTY, data, None)
        elif msg == SystemStatusMessageKind.STIMULUS_INPUTS:
            self.property_changed(MessageHandler.STIMULI_PROPERTY, data, None)
        elif msg == SystemStatusMessageKind.AUDIO_SPECTRUM:
            self._analysis.audio_spectrum_received(data)
            if self._audio_callback is not None:
                self._audio_callback(data.magnitudes)
        elif msg == SystemStatusMessageKind.MEASUREMENT or msg == SystemStatusMessageKind.MEASUREMENTS:
            weights, switch, pressure, temperature, humidity = self._analysis.measurements_received(
                data)
            if self._measurement_callback is not None:
                self._measurement_callback((weights, switch, pressure, temperature, humidity))
