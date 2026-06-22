import copy
import re
import time

import pytest

from autotrainer.core.capture import CaptureProcessStatus
from autotrainer.video import VideoRecordMode, VideoCapture, video_capture
from top_fixtures import collect_log_queue_to_caplog


@pytest.mark.parametrize("fps", (5, 30, 150))
def test_with_prebuffer(
    fps,
    video_capture_model,
    project_info,
    capture_multiprocess_logs,
    make_log_dict_multiproc,
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(video_capture, "make_log_dict_config", make_log_dict_multiproc)
    conf = video_capture_model.save_configuration()
    conf.params["primary"] = "true"
    conf.params["fps"] = fps
    video_capture_model.project = project_info
    conf.is_enabled = True
    conf.is_record_enabled = True
    conf.record_mode = VideoRecordMode.TRIGGER
    conf.record_prebuffer_duration = 2   # ensure not 0
    video_capture_model.load_configuration(conf)
    assert video_capture_model.on_prepare_capture() is True
    video_capture_model.on_capture_start()
    assert video_capture_model.wait_for_capture_status(CaptureProcessStatus.RUNNING, timeout=5) is True
    time.sleep(3)  # ensure prebuffer is filled enough
    video_capture_model.on_trigger_recording(True)
    time.sleep(1)
    assert video_capture_model.wait_for_capture_status(CaptureProcessStatus.RECORDING, timeout=5) is True
    video_capture_model.on_trigger_recording(False)
    assert video_capture_model.wait_for_capture_status(CaptureProcessStatus.RUNNING, timeout=5) is True
    # ensure _record_stop_sema has been released()/increased:
    assert video_capture_model._record_stop_sema.acquire(timeout=3) is True
    collect_log_queue_to_caplog(capture_multiprocess_logs)
    print(caplog.text)
    m = re.search(r"Closed video file: tot frames written: (\d+)", caplog.text)
    assert m is not None
    captured = int(m.group(1))
    assert fps * 3 <= captured < fps * 3.5
    # 2s of prebuffer, and 1s of recording duration :
    # so between 3 and 3.5s of capture


def test_with_primary_secondary(
    video_capture_model,
    project_info,
    capture_multiprocess_logs,
    make_log_dict_multiproc,
    monkeypatch,
    caplog,
):
    pass
    # TODO
