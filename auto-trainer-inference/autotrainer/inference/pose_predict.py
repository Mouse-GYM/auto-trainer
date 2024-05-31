import logging
import time
from enum import IntEnum
from multiprocessing import Process, Queue

import numpy

from autotrainer.core import FixedArrayMultiQueue
from .pose_model import PoseModel

logger = logging.getLogger(__name__)


class AnalysisMessageKind(IntEnum):
    Created = 0,
    Loading = 1,
    Initialized = 2,
    Running = 3,
    Terminated = 4,
    Performance = 5,
    Start = 6,
    Terminate = 7


class PosePredict(Process):

    def __init__(self, model: PoseModel, image_queue: FixedArrayMultiQueue, data_queue: Queue, cmd_queue: Queue,
                 msg_queue: Queue):
        super().__init__()

        self._model = model

        self._image_queue = image_queue
        self._cmd_queue = cmd_queue
        self._msg_queue = msg_queue
        self._data_queue = data_queue

        self._start_time = 0

        self._frame_count = 0

        self._pose_count = 0

        self._frame_buffer = None

    def run(self):
        logger.info("entering pose_predict")

        self._send_message(AnalysisMessageKind.Created)

        self._frame_buffer = numpy.ndarray((self._image_queue.batch_size, *self._image_queue.shape, 3))

        self._send_message(AnalysisMessageKind.Loading)

        self._model.load()

        try:
            self._send_message(AnalysisMessageKind.Initialized, self._model.body_parts)

            should_process = self._wait_for_start()

            if should_process:
                self._send_message(AnalysisMessageKind.Running)
                self._process()
        except Exception as ex:
            logger.error(ex)
        finally:
            self._send_message(AnalysisMessageKind.Terminated)

        logger.info("exiting pose_predict")

    def _send_message(self, kind: AnalysisMessageKind, context=None):
        if self._msg_queue:
            self._msg_queue.put((kind, context))

    '''
    Wait for Start or Terminate command.
    '''

    def _wait_for_start(self) -> bool:
        while True:
            try:
                cmd = self._cmd_queue.get_nowait()

                if cmd == AnalysisMessageKind.Terminate:
                    return False
                elif cmd == AnalysisMessageKind.Start:
                    break
            except:
                pass

        return True

    def _process(self):
        while True:
            try:
                cmd = self._cmd_queue.get_nowait()
                if cmd == AnalysisMessageKind.Terminate:
                    break
            except:
                pass

            if self._image_queue.get_output(self._frame_buffer):
                if self._frame_count == 0:
                    self._start_time = time.perf_counter()

                pose = self._model.predict(self._frame_buffer)

                if self._data_queue is not None:
                    self._data_queue.put(pose)

                self._pose_count += 1

                self._frame_count += self._image_queue.frames_per_camera

                if self._pose_count % 60 == 0:
                    now = time.perf_counter()
                    pps = self._pose_count / (now - self._start_time)
                    fps = self._frame_count / (now - self._start_time)
                    if self._msg_queue is not None:
                        self._msg_queue.put((AnalysisMessageKind.Performance, (pps, fps)))
                    logger.info(f"{pps :.1f} predict/s")
                    logger.info(f"{fps :.1f} frames/camera/s ({(fps * 2):.1f} total images/s)")
