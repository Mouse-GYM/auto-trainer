import time
from multiprocessing import Queue, Value, Array

from autotrainer.video import CaptureCameraAttrs, CaptureAttrs, VideoCapture
from autotrainer.core.capture import CaptureProcessStatus


def wait_for_status(status: Value, expected: CaptureProcessStatus, timeout: int):
    start_ns = time.perf_counter_ns()
    elapsed = 0

    while status.value != expected and elapsed < timeout:
        time.sleep(0.05)
        elapsed = (time.perf_counter_ns() - start_ns) / 1e9

    return elapsed <= timeout


def test_video_capture_invalid_camera():
    cmd_queue = Queue()
    image_queue = Queue()
    status = Value("i", CaptureProcessStatus.UNKNOWN)
    frame = Value("i", 0)
    errors = Array("c", bytes(512))

    camera = CaptureCameraAttrs(name="test", url="spinnaker://000000")

    attrs = CaptureAttrs(command_queue=cmd_queue, status=status, image_queue=image_queue, camera=camera,
                         frame=frame, errors=errors)

    process = VideoCapture(attrs)

    assert status.value == CaptureProcessStatus.INITIALIZED

    assert len(errors.value.decode()) == 0

    process.start()

    assert wait_for_status(status, CaptureProcessStatus.FAILED, timeout=4)

    assert len(errors.value.decode()) > 0
