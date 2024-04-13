import os
import sys
import time
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from threading import Thread

import cv2
import numpy


class VideoRecord(Thread):
    def __init__(self, output_location: str, name: str, interval: int, size: (int, int), fps: int, input_queue: Queue):
        Thread.__init__(self)

        self._output_location = output_location
        self._name = name
        self._interval = interval
        self._width = size[0]
        self._height = size[1]
        self._fps = fps
        self._input_queue = input_queue
        self._is_running = True
        self._record_start = None

        self._ext = ".mp4" if sys.platform.startswith("linux") else "mkv"

        self._writer = None
        self._timestamp = None

    def run(self) -> None:
        path = Path(self._output_location)
        path.mkdir(parents=True, exist_ok=True)

        self._update_writer()

        last_when = 0

        while self._is_running:
            try:
                (frame, when) = self._input_queue.get_nowait()

                if len(numpy.shape(frame)) < 3 or numpy.shape(frame)[2] == 1:
                    self._writer.write(numpy.tile(frame[:, :, numpy.newaxis], (1, 1, 3)))
                else:
                    self._writer.write(frame)

                if self._timestamp is not None:
                    self._timestamp.write(f"{when}, {1e9/(when - last_when)}\n")
                    last_when = when
            except Empty:
                time.sleep(0.0001)

            if time.time() - self._record_start > self._interval:
                self._update_writer()

        if self._writer is not None:
            self._writer.release()
        if self._timestamp is not None:
            self._timestamp.close()

    def cancel(self):
        self._is_running = False

    def _update_writer(self):
        if self._writer is not None:
            self._writer.release()
        if self._timestamp is not None:
            self._timestamp.close()

        self._record_start = time.time()

        file_timestamp = datetime.now()

        location = os.path.join(self._output_location,
                                f"{file_timestamp.strftime('%Y-%m-%d_%H-%M-%S')}_{self._name}.{self._ext}")

        self._timestamp = open(os.path.join(self._output_location,
                                            f"{file_timestamp.strftime('%Y-%m-%d_%H-%M-%S')}_{self._name}_timestamps.txt"), "w")

        self._writer = cv2.VideoWriter(location, cv2.VideoWriter_fourcc(*'mp4v'), self._fps,
                                       (self._width, self._height))
