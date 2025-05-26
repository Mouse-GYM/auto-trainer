import logging
import time
from enum import IntEnum
from multiprocessing import Process, Queue
from queue import Empty
from typing import Optional, Callable, List

import numpy

from autotrainer.core import FixedArrayMultiQueue, PerfMonitor
from autotrainer.core.logging import get_verbose_logger
from .pose_model import PoseModel

logger = get_verbose_logger(__name__)


class InferenceCommandMessageKind(IntEnum):
    Start = 0
    Terminate = 1
    ProcessLive = 2
    ProcessOffline = 3
    ProcessLiveWhenReady = 4
    SetLoggerLevel = 5


class InferenceStatusMessageKind(IntEnum):
    Created = 0
    Loading = 1
    Initialized = 2
    Running = 3
    Terminated = 4
    Performance = 5


class InferenceMode(IntEnum):
    Live = 0
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

    def __init__(self,
                 model: PoseModel,
                 live_queue: FixedArrayMultiQueue,
                 offline_queue: Optional[FixedArrayMultiQueue],
                 data_queue: Queue,
                 cmd_queue: Queue,
                 msg_queue: Queue,
    ):
        """
        :param model: the PoseModel instance
        :param live_queue: a FixedArrayMultiQueue as the default source of input frames
        :param offline_queue: an optional FixedArrayMultiQueue as a secondary source of input frames
        :param data_queue: an output Queue for pose data passed as tuple of pose data and the mode (live or offline)
        :param cmd_queue: an input Queue for starting, terminating, and changing queues
        :param msg_queue: an output Queue for status and performance messages
        """
        super().__init__(name=self.__class__.__name__)

        self._model = model

        self._live_input_queue = live_queue
        self._offline_input_queue = offline_queue
        self._cmd_queue = cmd_queue
        self._msg_queue = msg_queue
        self._data_queue = data_queue

        self._perf_monitor = PerfMonitor(name="<pose-predict>", units="predict calls/s", report_count=120,
                                         enable_log=False)

        self._mode = InferenceMode.Live
        self._input_queue = self._live_input_queue

        self._process_live_when_ready = False

    def run(self):
        from autotrainer.core.logging import setup_logging
        setup_logging()

        logger.info("entering pose_predict")
        self._send_message(InferenceStatusMessageKind.Created)

        self._send_message(InferenceStatusMessageKind.Loading)

        logging.root.setLevel(logging.WARN)
        self._model.load()
        logging.root.setLevel(logging.INFO)

        try:
            self._send_message(InferenceStatusMessageKind.Initialized, self._model.body_parts)
            should_process = self._wait_for_start()
            if should_process:
                self._send_message(InferenceStatusMessageKind.Running, InferenceMode.Live)
                self._process()
        except Exception as err:
            logger.exception("Error during processing: %s", err)
        finally:
            self._send_message(InferenceStatusMessageKind.Terminated)
        logger.notice("exiting pose_predict")

    def _send_message(self, kind: InferenceStatusMessageKind, context=None):
        if self._msg_queue:
            self._msg_queue.put((kind, context))

    def _set_process_live(self):
        logger.notice("processing live")
        self._input_queue = self._live_input_queue
        self._mode = InferenceMode.Live
        self._send_message(InferenceStatusMessageKind.Running, InferenceMode.Live)

    def _set_process_offline(self):
        logger.notice("processing offline")
        # self._input_queue = self._offline_input_queue
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
                else:
                    logger.warning("Unhandled command: %s", cmd)
            except Empty:
                # Unclear how universal this is, but the combination of [Jetson, JetPack 5, Ubuntu 20, Python] will
                # massively slow down the system without explicitly yielding, despite being in its own thread.  This not
                # the case for other platforms/combinations of the above so may not be apparent when not on the current
                # deployment platform.
                time.sleep(0.01)

        return True

    def _process(self):
        # import tensorflow as tf
        # gpus = tf.config.experimental.list_physical_devices('GPU')
        # for gpu in gpus:
        #     tf.config.experimental.set_memory_growth(gpu, True)
        frame_buffer = numpy.ndarray(
            (self._input_queue.batch_size,  # nbr cams * frames per cam (3 atm)
             *self._input_queue.shape,  # W, H
             3,  # current model takes RGB
             ))
        frames_indices = numpy.ndarray(
            (self._input_queue.camera_count, self._input_queue.frames_per_camera), dtype="int64")
        prev_mode = None
        logger.info("%s: starting processing ..", self)
        d_q_put = self._data_queue.put
        get_command = self._cmd_queue.get_nowait
        predict = self._model.predict
        perf_add_c = self._perf_monitor.add_cycle

        i_q_get_output: Optional[Callable] = None
        i_q: Optional[FixedArrayMultiQueue] = None

        def reset_locals():
            nonlocal i_q, i_q_get_output
            i_q = self._input_queue
            i_q_get_output = None if i_q is None else i_q.get_output

        reset_locals()

        t_next_cmd = time.time()
        while True:
            t_now = time.time()
            if t_now > t_next_cmd:
                # do not check command queue on each loop turn, mostly useless
                # and overhead is not that small
                t_next_cmd += 0.01
                for _ in range(4):  # assuming we don't get "burst" of commands
                    try:
                        cmd, context = get_command()
                    except Empty:
                        break
                    logger.info("Handling command %s ...", cmd)
                    try:
                        if cmd == InferenceCommandMessageKind.Terminate:
                            return
                        elif cmd == InferenceCommandMessageKind.ProcessLive:
                            self._set_process_live()
                        elif cmd == InferenceCommandMessageKind.ProcessOffline:
                            self._set_process_offline()
                        elif cmd == InferenceCommandMessageKind.ProcessLiveWhenReady:
                            self._process_live_when_ready = True
                        else:
                            logger.warning("Unhandled command: %s", cmd)
                    except Exception as err:
                        logger.warning("Error processing %s: %s", cmd, err)
                    # always get new ref:
                    prev_iq = i_q
                    reset_locals()
                    if prev_iq is not i_q:
                        logger.debug("new input_queue: %s / %s", i_q, i_q_get_output)

            # if prev_mode != self._mode:
            #     logger.notice("Detected change of mode: %s", self._mode)
            #     prev_mode = self._mode

            if i_q_get_output is not None and i_q_get_output(frame_buffer, frames_indices):
                if self._mode == InferenceMode.Offline and self._input_queue == self._live_input_queue and all(i < 0 for cam_fr_indices in frames_indices for i in cam_fr_indices):
                    self._input_queue = self._offline_input_queue
                    logger.notice("Switched to offline queue: %s", frames_indices)
                    # always get new ref:
                    reset_locals()
                    continue
                pose = predict(frame_buffer)
                # NB:
                # the data queue reader/consumer takes care of deciding what to do with the result data:
                d_q_put((pose,
                         InferenceMode.Live if self._input_queue == self._live_input_queue else InferenceMode.Offline,
                         frames_indices.copy(),  # getting frame indices corruption in reader side without this.
                         #  frames_indices,  # it could be eventually explained if the serialisation
                         # of the frames_indices numpy array happens after the return of the queue put()..
                         # which is not totally impossible.
                         ))
                if perf_add_c():
                    self._send_message(InferenceStatusMessageKind.Performance, self._perf_monitor.cps)

                if self._mode == InferenceMode.Offline and self._process_live_when_ready and (
                    all(idx < 0 for indices in frames_indices for idx in indices)
                ):
                    logger.notice("Detected end of offline queue processing")
                    self._offline_input_queue.reset_reader()  # reset our reader index for next offline
                    d_q_put((None, self._mode, None))  # tells data monitor this is EOF current offline data
                    self._set_process_live()  # set us to live processing
                    self._process_live_when_ready = False
                    # always get new ref:
                    reset_locals()
            else:
                # See sleep comment above.
                time.sleep(0.001)
        # end while True