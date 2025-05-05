import logging
import time
from enum import IntEnum
from multiprocessing import Process, Queue
from queue import Empty
from typing import Optional

import numpy

from autotrainer.core import FixedArrayMultiQueue, PerfMonitor
from .pose_model import PoseModel

logger = logging.getLogger(__name__)


class InferenceCommandMessageKind(IntEnum):
    Start = 0,
    Terminate = 1,
    ProcessLive = 2,
    ProcessOffline = 3,
    ProcessLiveWhenReady = 4


class InferenceStatusMessageKind(IntEnum):
    Created = 0,
    Loading = 1,
    Initialized = 2,
    Running = 3,
    Terminated = 4,
    Performance = 5


class InferenceMode(IntEnum):
    Live = 0,
    Offline = 1


class PoseProcess(Process):
    """
    Defines an independent Process for loading and processing a pose interference model.

    The primary behavior is to process frames from a "live" queue.  It is possible to toggle to between the primary and
    an optional secondary "offline" queue.  The purpose of the dual queues is to avoid contention between two different
    sources (having to turn one or both on or off from submitting to the queue, etc.).

    The PoseModel can be passed unloaded as it will be loaded in this separate Process.  Loaded values (such as part
    names) will not be available to the calling Process.  These values are provided as part of the Initialized status
    message.

    Live and Offline queues are FixedArrayMultiQueue instances that will drop batches based on the specified buffer
    depth.  The data, command, and message queues are standard multiprocessing.Queue instances that are not depth
    limited or defined with pre-allocated Array slots due to their expected small payload sizes.  Readers of the data
    and messages queues are expected to keep up with or drain the queues as needed.
    """

    def __init__(self, model: PoseModel, live_queue: FixedArrayMultiQueue,
                 offline_queue: Optional[FixedArrayMultiQueue], data_queue: Queue, cmd_queue: Queue, msg_queue: Queue):
        """
        :param model: the PoseModel instance
        :param live_queue: a FixedArrayMultiQueue as the default source of input frames
        :param offline_queue: an optional FixedArrayMultiQueue as a secondary source of input frames
        :param data_queue: an output Queue for pose data passed as tuple of pose data and the mode (live or offline)
        :param cmd_queue: an input Queue for starting, terminating, and changing queues
        :param msg_queue: an output Queue for status and performance messages
        """
        super().__init__()

        self._model = model

        self._live_input_queue = live_queue
        self._offline_input_queue = offline_queue
        self._cmd_queue = cmd_queue
        self._msg_queue = msg_queue
        self._data_queue = data_queue

        self._perf_monitor = PerfMonitor(name="<pose-predict>", units="predict calls/s", report_count=120,
                                         enable_log=False)

        self._frame_buffer = None

        self._mode = InferenceMode.Live
        self._input_queue = self._live_input_queue

        self._process_live_when_ready = False

    def run(self):
        logger.info("entering pose_predict")

        self._send_message(InferenceStatusMessageKind.Created)

        self._frame_buffer = numpy.ndarray((self._input_queue.batch_size, *self._input_queue.shape, 3))

        self._send_message(InferenceStatusMessageKind.Loading)

        self._model.load()

        try:
            self._send_message(InferenceStatusMessageKind.Initialized, self._model.body_parts)

            should_process = self._wait_for_start()

            if should_process:
                self._send_message(InferenceStatusMessageKind.Running, InferenceMode.Live)
                self._process()
        except Exception as ex:
            logger.error(ex)
        finally:
            self._send_message(InferenceStatusMessageKind.Terminated)

        logger.info("exiting pose_predict")

    def _send_message(self, kind: InferenceStatusMessageKind, context=None):
        if self._msg_queue:
            self._msg_queue.put((kind, context))

    def _set_process_live(self):
        logger.debug("processing live")
        self._input_queue = self._live_input_queue
        self._mode = InferenceMode.Live
        self._send_message(InferenceStatusMessageKind.Running, InferenceMode.Live)

    def _set_process_offline(self):
        logger.debug("processing offline")
        self._input_queue = self._offline_input_queue
        self._mode = InferenceMode.Offline
        self._send_message(InferenceStatusMessageKind.Running, InferenceMode.Offline)

    def _wait_for_start(self) -> bool:
        """
        Wait for Start or Terminate command.
        """
        while True:
            try:
                cmd, context = self._cmd_queue.get_nowait()

                if cmd == InferenceCommandMessageKind.Terminate:
                    return False
                elif cmd == InferenceCommandMessageKind.Start:
                    break
                elif cmd == InferenceCommandMessageKind.ProcessLive:
                    self._set_process_live()
                elif cmd == InferenceCommandMessageKind.ProcessOffline:
                    self._set_process_offline()
            except Empty:
                # Unclear how universal this is, but the combination of [Jetson, JetPack 5, Ubuntu 20, Python] will
                # massively slow down the system without explicitly yielding, despite being in its own thread.  This not
                # the case for other platforms/combinations of the above so may not be apparent when not on the current
                # deployment platform.
                time.sleep(0.0001)

        return True

    def _process(self):
        while True:
            try:
                cmd, context = self._cmd_queue.get_nowait()
            except Empty:
                pass
            else:
                try:
                    if cmd == InferenceCommandMessageKind.Terminate:
                        break
                    elif cmd == InferenceCommandMessageKind.ProcessLive:
                        self._set_process_live()
                    elif cmd == InferenceCommandMessageKind.ProcessOffline:
                        self._set_process_offline()
                    elif cmd == InferenceCommandMessageKind.ProcessLiveWhenReady:
                        self._process_live_when_ready = True
                except Exception as err:
                    logger.warning("Error processing %s: %s", cmd, err)

            if self._input_queue is not None:
                if self._input_queue.get_output(self._frame_buffer):
                    pose = self._model.predict(self._frame_buffer)

                    if self._data_queue is not None:
                        self._data_queue.put((pose, self._mode))

                    if self._perf_monitor.add_cycle():
                        self._send_message(InferenceStatusMessageKind.Performance, self._perf_monitor.cps)
                else:
                    if self._mode == InferenceMode.Offline and self._process_live_when_ready:
                        self._data_queue.put((None, self._mode))
                        self._set_process_live()
                        self._process_live_when_ready = False
            else:
                # See sleep comment above.
                time.sleep(0.001)
