from __future__ import annotations

import logging
import time
from enum import IntEnum
from multiprocessing import Process, Queue
from queue import Empty

import numpy

from autotrainer.core import FixedArrayMultiQueue, PerfMonitor
from .pose_model import PoseModel

logger = logging.getLogger(__name__)


class AnalysisCommandMessageKind(IntEnum):
    Start = 0,
    Terminate = 1,
    ProcessLive = 2,
    ProcessOffline = 3


class AnalysisStatusMessageKind(IntEnum):
    Created = 0,
    Loading = 1,
    Initialized = 2,
    Running = 3,
    Terminated = 4,
    Performance = 5


class AnalysisMode(IntEnum):
    Live = 0,
    Offline = 1


class PosePredict(Process):
    def __init__(self, model: PoseModel, live_queue: FixedArrayMultiQueue, offline_queue: FixedArrayMultiQueue | None,
                 data_queue: Queue, cmd_queue: Queue, msg_queue: Queue):
        super().__init__()

        self._model = model

        self._live_input_queue = live_queue
        self._offline_input_queue = offline_queue
        self._cmd_queue = cmd_queue
        self._msg_queue = msg_queue
        self._data_queue = data_queue
        self._width = 1
        self._height = 1

        self._perf_monitor = PerfMonitor(name="<pose-predict>", units="predict calls/s", report_count=120,
                                         enable_log=False)

        self._frame_buffer = None

        self._input_queue = self._live_input_queue

        # TODO Verify live and offline queues are the same size.

    def run(self):
        logger.info("entering pose_predict")

        self._send_message(AnalysisStatusMessageKind.Created)

        self._frame_buffer = numpy.ndarray((self._input_queue.batch_size, *self._input_queue.shape, 3))

        self._height, self._width = self._input_queue.shape

        self._send_message(AnalysisStatusMessageKind.Loading)

        self._model.load()

        try:
            self._send_message(AnalysisStatusMessageKind.Initialized, self._model.body_parts)

            should_process = self._wait_for_start()

            if should_process:
                self._send_message(AnalysisStatusMessageKind.Running, AnalysisMode.Live)
                self._process()
        except Exception as ex:
            logger.error(ex)
        finally:
            self._send_message(AnalysisStatusMessageKind.Terminated)

        logger.info("exiting pose_predict")

    def _send_message(self, kind: AnalysisStatusMessageKind, context=None):
        if self._msg_queue:
            self._msg_queue.put((kind, context))

    def _set_process_live(self):
        self._input_queue = self._live_input_queue
        self._send_message(AnalysisStatusMessageKind.Running, AnalysisMode.Live)

    def _set_process_offline(self):
        self._input_queue = self._offline_input_queue
        self._send_message(AnalysisStatusMessageKind.Running, AnalysisMode.Offline)

    def _wait_for_start(self) -> bool:
        """
        Wait for Start or Terminate command.
        """
        while True:
            try:
                cmd, context = self._cmd_queue.get_nowait()

                if cmd == AnalysisCommandMessageKind.Terminate:
                    return False
                elif cmd == AnalysisCommandMessageKind.Start:
                    break
                elif cmd == AnalysisCommandMessageKind.ProcessLive:
                    self._set_process_live()
                elif cmd == AnalysisCommandMessageKind.ProcessOffline:
                    self._set_process_offline()
            except Empty:
                time.sleep(0.0001)

        return True

    def _process(self):
        while True:
            try:
                cmd, context = self._cmd_queue.get_nowait()

                if cmd == AnalysisCommandMessageKind.Terminate:
                    break
                elif cmd == AnalysisCommandMessageKind.ProcessLive:
                    self._set_process_live()
                elif cmd == AnalysisCommandMessageKind.ProcessOffline:
                    self._set_process_offline()
            except:
                pass

            if self._input_queue is not None:
                if self._input_queue.get_output(self._frame_buffer):
                    pose = self._model.predict(self._frame_buffer)

                    # Normalize locations.  Not all consumers will be scaling the location by the original frame size.
                    for frame in pose:
                        frame[:, 0] /= self._width
                        frame[:, 1] /= self._height

                    if self._data_queue is not None:
                        self._data_queue.put(pose)

                    if self._perf_monitor.add_cycle():
                        self._send_message(AnalysisStatusMessageKind.Performance, self._perf_monitor.cps)
            else:
                time.sleep(0.001)
