from queue import Queue

from .device_reader import DeviceReader
from .pellet_delivery import PelletDeliveryMessageKind


class PelletReader(DeviceReader):
    def __init__(self, input_queue: Queue):
        super().__init__(input_queue, name="PelletReader")

    def message_received(self, msg, data):
        if msg == PelletDeliveryMessageKind.UPDATE_X:
            self.property_changed("device_x", data, None)
        if msg == PelletDeliveryMessageKind.UPDATE_Y:
            self.property_changed("device_y", data, None)
        if msg == PelletDeliveryMessageKind.UPDATE_Z:
            self.property_changed("device_z", data, None)
