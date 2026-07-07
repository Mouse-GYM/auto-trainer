
import multiprocessing
import sys
import threading
import time
from functools import partial
from pathlib import Path

import cv2
import numpy
import pytest

from autotrainer.behavior import SegmentationConfiguration
from autotrainer.core import FixedArrayMultiQueue, FrameIndexCategory
from autotrainer.inference import InferenceCommandMessageKind, InferenceStatus
from tools.acquisition.model.inference_model import InferenceModel


@pytest.fixture()
def inference(pose_algo, calib_dir, project_info, mp_manager):
    record_stop_sema = multiprocessing.Semaphore()
    model = InferenceModel(
        pose_algo,
        calib_dir=calib_dir, record_stop_sema=record_stop_sema, mp_manager=mp_manager)
    model.project = project_info
    try:
        yield model
    finally:
        model.terminate()
        model = None  # noqa


@pytest.fixture()
def inference_q():
    q = FixedArrayMultiQueue(3, 2, 3, (300, 200))
    return q


def test_inference_recording_and_offline_processing(
    project_info,
    inference,
    inference_q,
    make_log_dict_multiproc,
    monkeypatch,
):
    fps = 50
    frame_width = inference_q.shape[1]
    frame_height = inference_q.shape[0]
    monkeypatch.setattr(sys.modules[inference.__module__], "make_log_dict_config", make_log_dict_multiproc)
    inference.start(inference_q)
    ts = project_info.get_trial_path()
    Path(ts.location).mkdir(parents=True)
    frame = numpy.ndarray(inference_q.shape, dtype=numpy.uint8)
    fidx = FrameIndexCategory.ONLINE_NO_RECORDING
    # need put at least one frame batch/block to make pose-process emit its "live" status:
    inference_q.put_frame_index_category(frame, fidx)
    inference.wait_for_status(InferenceStatus.live, timeout=5)
    # print(inference.project)
    vws = []
    cams = (project_info.camera_1, project_info.camera_2)
    for cdx in range(2):
        vw = cv2.VideoWriter()
        vid_p, ts_p, frames_processed_p = project_info.get_video_path(cams[cdx])
        vw.open(vid_p, cv2.VideoWriter_fourcc(*'mp4v'), fps, (frame_width, frame_height))
        vws.append(vw)
    tot_put = 0
    for fidx in range(0, 150):
        for cdx in range(2):
            vw = vws[cdx]
            vw.write(numpy.tile(frame[:, :, numpy.newaxis], (1, 1, 3)))
            if fidx % 3 == 0:
                inference_q.put(frame, cdx, fidx, timeout=30)
                if cdx == 0:
                    tot_put += 1
    pads = []
    for cdx in range(2):
        th = threading.Thread(target=lambda cdx=cdx: inference_q.pad_to_batch_size(cdx, frame, tot_put))
        th.start()
        pads.append(th)
        vw = vws[cdx]
        vw.release()
    for th in pads:
        th.join()
    inference_q.put_frame_index_category(frame, FrameIndexCategory.EOF_RECORDING)
    wait_stop_recorded = False
    def on_complete(success, *, error="NA"):
        pass
    cfg = SegmentationConfiguration(project=project_info, frame_rate=fps, complete=on_complete)
    assert inference.perform_segmentation(cfg) is not None
    time.sleep(2.5)
    inference.send_message(InferenceCommandMessageKind.ProcessOffline, (project_info, wait_stop_recorded))
    time.sleep(5)
    inference.send_message(InferenceCommandMessageKind.SetOfflineToLive)
    time.sleep(2)
