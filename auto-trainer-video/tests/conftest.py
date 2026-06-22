import ctypes
import multiprocessing
from multiprocessing import Queue, Value, Array

import pytest

from autotrainer.video import CaptureCameraAttrs, CaptureAttrs, VideoCapture
from autotrainer.core.capture import CaptureProcessStatus
from tools.acquisition.model.video_capture_model import VideoCaptureModel


@pytest.fixture
def video_capture():
    cmd_queue = Queue()
    image_queue = Queue()
    status = Value("i", CaptureProcessStatus.UNKNOWN)
    frame = Value(ctypes.c_int64, 0)
    errors = Array(ctypes.c_char, bytes(512))

    record_stop_sema = multiprocessing.Semaphore(0)

    camera = CaptureCameraAttrs(name="test", url="spinnaker://000000")

    attrs = CaptureAttrs(
        command_queue=cmd_queue,
        status=status,
        image_queue=image_queue,
        camera=camera,
        frame=frame,
        errors=errors,
        record_stop_sema=record_stop_sema,
    )

    process = VideoCapture(attrs)
    try:
        yield process
    finally:
        process.terminate()
        if process.exitcode is not None:
            process.join(1)


@pytest.fixture
def video_capture_model(user_pref) -> VideoCaptureModel:  # noqa
    model = VideoCaptureModel(
        name="test_cam1",
        preferences=user_pref,
        camera_index=0,
        msg_queue=multiprocessing.Queue(),  # : Optional[multiprocessing.Queue] = None,
        # presence_detection: Optional[PresenceDetectionAttrs] = None,
        synced_cam_recording=multiprocessing.Value(ctypes.c_bool, False),
        synced_cam_frame_index=multiprocessing.Value(ctypes.c_int64, 0),
        record_stop_sema=multiprocessing.Semaphore(0),
    )
    try:
        yield model  # noqa
    finally:
        model.on_close()
