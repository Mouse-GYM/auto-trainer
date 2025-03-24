from queue import Queue

from autotrainer.core import SystemStatusMessageKind

from .device_reader import DeviceReader


class PelletReader(DeviceReader):
    def __init__(self, input_queue: Queue):
        super().__init__(input_queue, name="PelletReader")

    def message_received(self, msg, data):
        if msg == SystemStatusMessageKind.UPDATE_X:
            self.property_changed("device_x", data, None)
        if msg == SystemStatusMessageKind.UPDATE_Y:
            self.property_changed("device_y", data, None)
        if msg == SystemStatusMessageKind.UPDATE_Z:
            self.property_changed("device_z", data, None)
