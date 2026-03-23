# process pool usage for live inference 3d-triangulation

import functools
import multiprocessing
from typing import Optional

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import pool_init
from autotrainer.inference import PoseAlgorithm, InferenceMonitorDataMsg


logger = get_verbose_logger(__name__)


_output_data_queue: Optional[multiprocessing.Queue] = None
_pose_algo_process = None


def pool_init_process_pose_data(pose_algo: PoseAlgorithm, output_data_queue, monitored_parts_offsets, log_config):
    pool_init(log_config)
    global _pose_algo_process, _output_data_queue
    _output_data_queue = output_data_queue
    _pose_algo_process = functools.partial(pose_algo.process, pairs_3d_offsets=monitored_parts_offsets)
    logger.success("Initialized with %s and %s", pose_algo, monitored_parts_offsets)


def pool_process_pose_data(pose_data):
    # logger.debug("received workload %s", type(pose_data))
    rsp = _pose_algo_process(pose_data)  # noqa
    # (cmd, (args, kwargs)) :
    _output_data_queue.put((InferenceMonitorDataMsg.POSE_RESULT_READY, ((rsp,), None)))
    # same as _send_msg in InferenceMonitorDataProc.
