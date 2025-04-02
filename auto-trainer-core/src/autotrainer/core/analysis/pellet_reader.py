from queue import Queue

from autotrainer.core import SystemStatusMessageKind

from .device_reader import DeviceReader


class PelletReader(DeviceReader):
    # This class responds to messages coming from the hardware that are specific to pellet delivery.

    # TODO: Some forced property change events rather than actual properties among other shortcuts at the moment.
    def __init__(self, input_queue: Queue):
        super().__init__(input_queue, name="PelletReader")

    def message_received(self, msg, data):
        if msg == SystemStatusMessageKind.PELLET_X:
            self.property_changed("device_x", data, None)
        if msg == SystemStatusMessageKind.PELLET_Y:
            self.property_changed("device_y", data, None)
        if msg == SystemStatusMessageKind.PELLET_Z:
            self.property_changed("device_z", data, None)
        if msg == SystemStatusMessageKind.PELLET_LOAD:
            self.property_changed("load_angle", data, None)
        if msg == SystemStatusMessageKind.PELLET_COVER:
            self.property_changed("cover_angle", data, None)
