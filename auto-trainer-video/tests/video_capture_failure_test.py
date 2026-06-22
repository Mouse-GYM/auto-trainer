import time
from multiprocessing import Queue, Value, Array

from autotrainer.core.capture import CaptureProcessStatus


def wait_for_status(status: Value, expected: CaptureProcessStatus, timeout: int):
    start_ns = time.perf_counter_ns()
    elapsed = 0

    while status.value != expected and elapsed < timeout:
        time.sleep(0.05)
        elapsed = (time.perf_counter_ns() - start_ns) / 1e9

    return elapsed <= timeout


def test_video_capture_invalid_camera(video_capture):

    assert video_capture._status.value == CaptureProcessStatus.INITIALIZED

    assert len(video_capture._errors.value.decode()) == 0

    video_capture.start()

    assert wait_for_status(video_capture._status, CaptureProcessStatus.FAILED, timeout=4)

    assert len(video_capture._errors.value.decode()) > 0
