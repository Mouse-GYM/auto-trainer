import logging.config
import signal
import threading
import time
from enum import IntEnum
from multiprocessing import Process, Queue
from queue import Empty
from typing import Optional, Callable, List, Dict

import numpy
import numpy as np

from autotrainer.core import FixedArrayMultiQueue, PerfMonitor
from autotrainer.core.logging import get_verbose_logger, get_multiprocess_log_queue, make_log_dict_config, \
    setup_logging, install_log_exception_hook
from autotrainer.core.message import FrameIndexCategory
from . import DlcPoseModel, MemoryPoseModel
from .pose_model import PoseModel


logger = get_verbose_logger(__name__)


class InferenceCommandMessageKind(IntEnum):
    Start = 0
    Terminate = 1
    ProcessLive = 2  # nb: not anymore used as command message.
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

    def __init__(
        self,
        live_queue: FixedArrayMultiQueue,
        offline_queue: Optional[FixedArrayMultiQueue],
        data_queue: Queue,
        cmd_queue: Queue,
        msg_queue: Queue,
        *,
        model_location: str,
    ):
        """
        :param model: the PoseModel instance
        :param live_queue: a FixedArrayMultiQueue as the default source of input frames
        :param offline_queue: an optional FixedArrayMultiQueue as a secondary source of input frames
        :param data_queue: an output Queue for pose data passed as tuple of pose data and the mode (live or offline)
        :param cmd_queue: an input Queue for starting, terminating, and changing queues
        :param msg_queue: an output Queue for status and performance messages
        """
        log_dict_config = make_log_dict_config()
        super().__init__(
            name=self.__class__.__name__,
            target=self._do_run,
            kwargs=dict(log_dict_config=log_dict_config),
            daemon=True,
        )

        self._pose_model: PoseModel
        self._model_location = model_location

        self._live_input_queue = live_queue
        self._offline_input_queue = offline_queue
        self._cmd_queue = cmd_queue
        self._msg_queue = msg_queue
        self._data_queue = data_queue

        self._perf_monitor = PerfMonitor(name="<pose-predict>", units="predict calls/s", report_window=30,
                                         enable_log=False)

        self._mode = InferenceMode.Live
        self._input_queue = self._live_input_queue

        self._process_live_when_ready = False
        self._is_running = True

    def _do_run(self, *, log_dict_config: Optional[Dict]):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        if log_dict_config is None:
            setup_logging()
        else:
            logging.config.dictConfig(log_dict_config)
            install_log_exception_hook()

        logger.info("started with %s", log_dict_config)
        try:
            self.__do_run()
        except BaseException as err:
            logger.exception("Fatal error: %s", err)

    def __do_run(self):
        self._send_message(InferenceStatusMessageKind.Created)

        model_path = self._model_location
        if model_path is None or len(model_path) == 0:
            logger.warning("pellet model not specified; using in-memory random data")
            model = MemoryPoseModel(self._live_input_queue.batch_size)
        else:
            logger.notice("Loading DLC model %r", model_path)
            model = DlcPoseModel(model_path, 1, 0, self._live_input_queue.batch_size)

        if not model.is_valid():
            logger.critical("pellet not started because the model does not exist or is not valid"
                           " at the specified location: %s", model_path)
            raise RuntimeError(f"Model at {model_path} not valid")

        self._pose_model = model

        self._send_message(InferenceStatusMessageKind.Loading)

        prev_lvl = logging.root.level
        logging.root.setLevel(logging.WARN)
        self._pose_model.load()
        logging.root.setLevel(prev_lvl)

        try:
            self._send_message(InferenceStatusMessageKind.Initialized, self._pose_model.body_parts)
            should_process = self._wait_for_start()
            if should_process:
                thread = threading.Thread(target=self._handle_cmd_queue, daemon=True, name="CmdQueueHandler")
                thread.start()
                logger.info("entering pose_predict")
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
        logger.notice("setting processing live")
        self._input_queue = self._live_input_queue
        self._mode = InferenceMode.Live
        self._send_message(InferenceStatusMessageKind.Running, InferenceMode.Live)

    def _set_process_offline(self):
        logger.notice("got processing offline")
        # self._input_queue = self._offline_input_queue
        # do not change immediately the used input queue to offline,
        # we'll wait the camera capture sends the EOF_RECORDING frame index batch,
        # so that we process entirely the live queue up to eof_recording,
        # handling all possible live recorded frames.
        self._mode = InferenceMode.Offline

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
                    self._input_queue = self._offline_input_queue
                else:
                    logger.warning("Unhandled command: %s", cmd)
            except Empty:
                time.sleep(0.01)

        return True

    def _handle_cmd_queue(self):
        while True:
            try:
                cmd, context = self._cmd_queue.get(timeout=1)
            except Empty:
                continue
            logger.info("Handling command %s ...", cmd)
            try:
                if cmd == InferenceCommandMessageKind.Terminate:
                    self._is_running = False
                    return
                elif cmd == InferenceCommandMessageKind.ProcessLive:
                    # not anymore used from main process.
                    # we rely on FrameIndexCategory
                    # self._set_process_live()
                    logger.verbose("Ignoring InferenceCommandMessageKind.ProcessLive")
                elif cmd == InferenceCommandMessageKind.ProcessOffline:
                    self._set_process_offline()
                elif cmd == InferenceCommandMessageKind.ProcessLiveWhenReady:
                    # NB: not anymore used actually.
                    self._process_live_when_ready = True
                else:
                    logger.warning("Unhandled command: %s", cmd)
            except Exception as err:
                logger.warning("Error processing %s: %s", cmd, err)

    def _process(self):
        # import tensorflow as tf
        # gpus = tf.config.experimental.list_physical_devices('GPU')
        # for gpu in gpus:
        #     tf.config.experimental.set_memory_growth(gpu, True)
        sent_live = False  # on first processed capture
        frame_buffer = numpy.ndarray(
            (self._input_queue.batch_size,  # nbr cams * frames per cam (3 atm)
             *self._input_queue.shape,  # W, H
             3,  # current model takes RGB
             ))
        frames_indices = numpy.ndarray(
            (self._input_queue.camera_count, self._input_queue.frames_per_camera), dtype="int64")
        # use a pre-allocated copy for outputting the frames indices:
        frames_indices_out = frames_indices.copy()
        prev_mode = None
        logger.info("%s: starting processing ..", self)
        d_q_put = self._data_queue.put
        predict = self._pose_model.predict
        perf_add_c = self._perf_monitor.add_cycle

        i_q: Optional[FixedArrayMultiQueue] = None

        def reset_locals():
            nonlocal i_q
            i_q = self._input_queue

        reset_locals()

        p_last_data = time.perf_counter()

        while self._is_running:
            p_now = time.perf_counter()

            if prev_mode != self._mode:
                logger.notice("Detected change of mode: %s", self._mode)
                prev_mode = self._mode

            # should be removed once more confident
            if i_q is self._offline_input_queue and p_now > p_last_data + 15:
                logger.warning("timeout waiting offline data ; auto-switching to online")
                self._set_process_live()
                reset_locals()

            if not i_q.get_output(frame_buffer, frames_indices):
                time.sleep(0.001)
                continue

            p_last_data = p_now
            mode_used = InferenceMode.Live if i_q is self._live_input_queue else InferenceMode.Offline

            if (frames_indices[:, -1] < 0).any():
                if __debug__:
                    if not (frames_indices == FrameIndexCategory.ONLINE_NO_RECORDING).all():
                        logger.debug("mode=%s prev=%s indices=%s", self._mode, prev_mode, frames_indices.tolist())

                if (
                    i_q is self._offline_input_queue
                    and numpy.isin(frames_indices[:, -1], [ # noqa
                        FrameIndexCategory.ONLINE_NO_RECORDING,
                        FrameIndexCategory.SWITCH_TO_ONLINE]
                    ).any()
                ):
                    self._set_process_live()
                    reset_locals()
                # elif required, given _set_process_live called in previous if block:
                elif (
                    i_q is self._live_input_queue
                    and (frames_indices[:, -1] == FrameIndexCategory.EOF_RECORDING).any()
                ):
                    self._input_queue = self._offline_input_queue
                    self._mode = InferenceMode.Offline
                    logger.notice("Switched to offline queue: %s", frames_indices.tolist())
                    self._send_message(InferenceStatusMessageKind.Running, InferenceMode.Offline)
                    # always get new ref:
                    reset_locals()

            # only predict for not fully incomplete frames buffer:
            if (frames_indices >= FrameIndexCategory.ONLINE_NO_RECORDING).any():
                pose = predict(frame_buffer)
            else:
                logger.debug("indices=%s skipped inference", frames_indices.tolist())
                # otherwise gives a full "0" result:
                # * 3 : for X, Y and confidence
                pose = [np.asarray([0] * 3 * len(self._pose_model.body_parts))] * frames_indices.size
                # that will anyway be skipped in the consumer when needed

            frames_indices_out[:] = frames_indices
            # getting frame indices corruption in reader side without this.
            # It could be eventually explained if the serialisation
            # of the frames_indices numpy array happens after the return of the queue put()..
            # which is not totally impossible.

            # NB:
            # the data queue reader/consumer takes care of deciding what to do with the result data:
            d_q_put((pose,
                     mode_used,
                     frames_indices_out,
                     ))

            if not sent_live:
                self._send_message(InferenceStatusMessageKind.Running, InferenceMode.Live)
                sent_live = True

            if perf_add_c():
                self._send_message(InferenceStatusMessageKind.Performance, self._perf_monitor.cps)

            if mode_used == InferenceMode.Offline and (
                frames_indices[:, -1] == FrameIndexCategory.EOF_OFFLINE_PROCESSING
            ).any():
                logger.notice("Detected end of offline queue processing: %s", frames_indices.tolist())
                # self._offline_input_queue.reset_reader()  # reset our reader index for next offline
                d_q_put((None, InferenceMode.Offline, None))  # tells data monitor this is EOF current offline data
                # then swap to live queue
                self._set_process_live()  # set us to live processing
                # self._process_live_when_ready = False
                # always get new ref:
                reset_locals()

        # end while True
