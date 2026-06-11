# process pool usage for live inference 3d-triangulation

import sys
import functools
import multiprocessing.managers
import queue
import signal
import logging.config
from typing import Optional, Union, Dict, List, Tuple

from autotrainer.core.logging import (
    get_verbose_logger,
    setup_logging,
    install_log_exception_hook,
    make_log_dict_config,
)
from autotrainer.core.multiproc import pool_init, get_mp_ctx
from autotrainer.inference import PoseAlgorithm, InferenceMonitorDataMsg


logger = get_verbose_logger(__name__)


class LivePoseResultProcessWorker(multiprocessing.Process):

    def __init__(
        self,
        *,
        pose_algo: PoseAlgorithm,
        monitored_parts_offsets: List[Tuple[str, str]],
        input_q: multiprocessing.Queue,
        output_q: multiprocessing.Queue,
        generation: int,
    ):
        super().__init__(name="LivePoseProcess", daemon=True)
        self._log_dict_config = make_log_dict_config()
        mp_ctx = get_mp_ctx()
        self._is_ready_event = mp_ctx.Event()
        self._stop_requested = mp_ctx.Event()
        self._input_q = input_q
        self._pose_algo = pose_algo
        self._monitored_parts_offsets = monitored_parts_offsets
        self._output_q = output_q
        self._generation = generation
        logger.debug("starting %s", self)
        self.start()
        logger.verbose("started ok %s", self)

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def pose_algo(self) -> PoseAlgorithm:
        return self._pose_algo

    def is_ready(self):
        return self._is_ready_event.is_set()

    def request_stop(self):
        if self.is_alive():
            self._stop_requested.set()
        else:
            self.join(0)  # just to ensure collect the exit code
            logger.warning("worker already stopped: %s", self)

    def run(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        log_dict_config = self._log_dict_config
        if log_dict_config is None:
            setup_logging(logger_level=logging.DEBUG)
        else:
            logging.config.dictConfig(log_dict_config)
            install_log_exception_hook()
        logger.verbose("setting ready to work")
        self._is_ready_event.set()
        warn_full = False
        while True:
            if self._stop_requested.is_set():
                break
            try:
                pose_data = self._input_q.get(timeout=0.1)
            except queue.Empty:
                continue
            rsp = self._pose_algo.process(pose_data, pairs_3d_offsets=self._monitored_parts_offsets)
            data = (
                InferenceMonitorDataMsg.POSE_RESULT_READY,  # cmd
                ((rsp,), None)  # args, kwargs
            )
            try:
                self._output_q.put(data, block=False)
            except queue.Full:
                if not warn_full:
                    warn_full = True
                    logger.warning("output queue full")
            else:
                warn_full = False
        logger.debug("exiting")