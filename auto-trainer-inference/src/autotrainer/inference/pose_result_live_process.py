# process pool usage for live inference 3d-triangulation

import sys
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
_consecutive_output_queue_full_count = 0


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
    global _consecutive_output_queue_full_count
    # logger.debug("received workload %s ; q=%s - %s", type(pose_data), q, type(q))
    if _output_data_queue is None:
        raise RuntimeError("unconfigured pool worker")
    rsp = _pose_algo_process(pose_data)  # noqa
    data = (
        InferenceMonitorDataMsg.POSE_RESULT_READY,  # cmd
        ((rsp,), None)  # args, kwargs
    )
    # this is used for live processing,
    # prefer to not block, so that if consumer (main process) becomes too slow for some reason,
    # this will possibly help that.
    try:
        _output_data_queue.put(data, block=False)
    except queue.Full:
        logger.verbose("output queue full, skipped data")
        _consecutive_output_queue_full_count += 1
        if _consecutive_output_queue_full_count > 32:
            sys.exit(-1)  # make the worker to exit, normally
            # raise RuntimeError(f"too many consecutive queue put full {_consecutive_output_queue_full_count}")
    else:
        _consecutive_output_queue_full_count = 0
    # same as _send_msg in InferenceMonitorDataProc.
