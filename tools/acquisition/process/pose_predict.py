import os
import time
from multiprocessing import Process

import numpy

from autotrainer.dlc.dlc_configuration import DLCConfiguration


class PosePredict(Process):

    def __init__(self, input_queue, network):
        super().__init__()

        self._input_queue = input_queue

        self._frames_per_buffer = 5

        self._cameras_per_buffer = 2

        self._batch_size = self._frames_per_buffer * self._cameras_per_buffer

        self._frame_count = 0

        self._start_time = 0

        self._frame_buffer_index = 0

        self._network = network

        self._frame_buffer = None

        self._configuration = None

    def run(self):
        self._frame_buffer = numpy.ndarray((10, 200, 300, 3))

        self._configuration = DLCConfiguration()

        self._configuration.load_configuration(os.path.join(self._network, "config.yaml"), 1, 0, self._batch_size)

        self._configuration.predict(self._frame_buffer)

        while True:
            image_1, image_2 = self._input_queue.get()

            if self._frame_count == 0:
                self._start_time = time.perf_counter()

            self._frame_buffer[self._frame_buffer_index, :, :, :] = numpy.tile(image_1[:, :, numpy.newaxis], (1, 1, 3))
            self._frame_buffer[self._frame_buffer_index + 1, :, :, :] = numpy.tile(image_2[:, :, numpy.newaxis], (1, 1, 3))

            self._frame_buffer_index += 2

            if self._frame_buffer_index >= self._batch_size:
                # pose = self._configuration.predict(self._frame_buffer)
                self._frame_buffer_index = 0

            self._frame_count += 1

            if self._frame_count % 200 == 0:
                print(f"{(self._frame_count / (time.perf_counter() - self._start_time)):.1f}")
                print(f"{self._input_queue.qsize()}")
