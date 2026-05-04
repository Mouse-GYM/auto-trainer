# process pool usage for live inference 3d-triangulation

import functools
import multiprocessing
import queue
from typing import Optional, Union

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import pool_init
from autotrainer.inference import PoseAlgorithm, InferenceMonitorDataMsg


logger = get_verbose_logger(__name__)


_output_data_queue: Optional[Union[queue.Queue, multiprocessing.Queue]] = None
_pose_algo_process = None


def pool_init_process_pose_data(pose_algo: PoseAlgorithm, output_data_queue, monitored_parts_offsets, log_config):
    pool_init(log_config)
    global _pose_algo_process, _output_data_queue
    _output_data_queue = output_data_queue
    # interestingly the output_data_queue we get here is a `queue.Queue` ; ie a thread queue,
    # while the one which is passed to this process pool init func is a `multiprocessing.Queue`,
    # might be on this receiving side it's wrapped into such a thread queue proxy eventually...
    _pose_algo_process = functools.partial(pose_algo.process, pairs_3d_offsets=monitored_parts_offsets)
    logger.success("Initialized with %s and %s ; q=%s", pose_algo, monitored_parts_offsets, output_data_queue)


def pool_process_pose_data(pose_data):
    # logger.debug("received workload %s ; q=%s - %s", type(pose_data), q, type(q))
    if _output_data_queue is None:
        raise RuntimeError("unconfigured pool worker")
    rsp = _pose_algo_process(pose_data)  # noqa
    # (cmd, (args, kwargs)) :
    _output_data_queue.put((InferenceMonitorDataMsg.POSE_RESULT_READY, ((rsp,), None)))
    # same as _send_msg in InferenceMonitorDataProc.
