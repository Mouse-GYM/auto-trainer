from queue import Queue

from .device_reader import DeviceReader


class PelletReader(DeviceReader):
    def __init__(self, input_queue: Queue):
        super().__init__(input_queue, name="PelletReader")
