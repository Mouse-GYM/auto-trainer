import logging
import queue
from queue import Queue
from enum import Enum
from multiprocessing import Process

from .video_manager import VideoManager
from .video_record import VideoRecord
from .video_record_properties import VideoRecordProperties, VideoRecordMode

logger = logging.getLogger(__name__)


class CaptureMessageKind(Enum):
    END_CAPTURE_ACKNOWLEDGE = -7,
    END_CAPTURE = -6,
    BEGIN_CAPTURE_ACKNOWLEDGE = -5,
    BEGIN_CAPTURE = -4,
    TRIGGER = -3,
    TERMINATE = -2,
    TERMINATED = -1


class VideoCapture(Process):
    def __init__(self, name, cmd_message_queue, status_message_queue, image_queue, network_queue, camera_url: str,
                 cam_idx: int = None, record_properties: VideoRecordProperties = None):
        super().__init__(name=name)

        self._name = name
        self._cmd_message_queue = cmd_message_queue
        self._status_message_queue = status_message_queue
        self._image_queue = image_queue
        self._network_queue = network_queue
        self._camera_url = camera_url
        self._camera_idx = cam_idx

        if record_properties is None:
            self._is_record_enabled = False
            self._is_record_triggered = False
            self._record_location = ""
            self._record_interval = 60
        else:
            self._is_record_enabled = record_properties.record_mode != VideoRecordMode.NONE
            self._is_record_triggered = record_properties.record_mode == VideoRecordMode.CONTINUOUS
            self._record_location = record_properties.output_location
            self._record_interval = record_properties.interval

        self._is_running = True
        self._is_capturing = False
        self._camera = None
        self._record_queue = None

        self.message_handler = {
            CaptureMessageKind.TERMINATE: self._user_terminate,
            CaptureMessageKind.BEGIN_CAPTURE: self._begin_capture,
            CaptureMessageKind.END_CAPTURE: self._end_capture,
            CaptureMessageKind.TRIGGER: self._record_trigger
        }

    def run(self):
        logger.debug(f"<{self._name}> process started")

        if self._camera_url is None:
            logger.error(f"<{self._name}> camera url not specified")
            return

        VideoManager.open()

        self.create_camera()
        self._camera.prepare_capture()

        record = None

        if self._is_record_enabled:
            self._record_queue = Queue()
            record = VideoRecord(self._record_location, self._name, self._record_interval,
                                 (self._camera.width, self._camera.height), self._camera.fps, self._record_queue)
            record.start()

        if self._status_message_queue is not None:
            self._status_message_queue.put(CaptureMessageKind.BEGIN_CAPTURE_ACKNOWLEDGE)

        while self._is_running:
            if self._cmd_message_queue is not None:
                try:
                    msg = self._cmd_message_queue.get(False)
                    self._handle_message(msg)
                except queue.Empty:
                    pass

            if not self._is_capturing or self._image_queue is None:
                continue

            frame, when = self._camera.capture()

            self._image_queue.put(frame)

            if self._is_record_enabled and self._is_record_triggered:
                self._record_queue.put((frame, when))

            if self._network_queue is not None:
                self._network_queue.put(frame, self._camera_idx)

        logger.debug(f"<{self._name}> capture loop ended")

        self._camera.end_capture()

        VideoManager.close()

        if record is not None:
            record.cancel()
            record.join()

        if self._status_message_queue is not None:
            self._status_message_queue.put(CaptureMessageKind.TERMINATED)

        logger.debug(f"<{self._name}> terminated")

    def create_camera(self):
        self._camera = VideoManager.create_camera(self._camera_url, self._name)

    def _handle_message(self, message):
        logger.debug(f"<{self._name}> {message}")
        self.message_handler.get(message)()

    def _user_terminate(self):
        self._is_running = False

    def _begin_capture(self):
        self._is_capturing = True

    def _end_capture(self):
        self._is_capturing = False

    def _record_trigger(self):
        self._is_record_triggered = not self._is_record_triggered
