import time
from multiprocessing import Queue

from PySide6.QtCore import QThread, QTimer
from numpy import ndarray

from autotrainer.video_capture import VideoCapture, CaptureMessageKind
from autotrainer.video_record_properties import VideoRecordProperties, VideoRecordMode
from autotrainer.video_manager import VideoManager
from autotrainer.trigger_manager import TriggerManager

from tools.acquisition.process.video_reader import VideoReader

CAPTURE_TRIGGER_ID = "CaptureTrigger"


class VideoCaptureModel:
    def __init__(self, name, network_queue=None):
        super().__init__()

        self._name = name

        self.video_reader = None
        self._video_reader_thread = None
        self._video_capture = None

        self._video_cmd_message_queue = Queue()
        self._video_status_message_queue = Queue()
        self._video_queue = Queue()
        self._network_queue = network_queue

        self._display_update_fcn = None

        self._frame_count = 0

        self._start = 0

        self._fps = 0

        self._is_enabled = True

        self._record_mode = VideoRecordMode.NONE

        self._is_recording_enabled = False

        self._camera_source = None

        self._is_primary = False

        TriggerManager.instance().register(self._on_trigger, CAPTURE_TRIGGER_ID)

    @property
    def camera_source(self) -> str:
        return self._camera_source

    @camera_source.setter
    def camera_source(self, value: str):
        self._camera_source = value

    @property
    def is_enabled(self):
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value):
        self._is_enabled = value

    @property
    def record_mode(self) -> VideoRecordMode:
        return self._record_mode

    @record_mode.setter
    def record_mode(self, value: VideoRecordMode):
        self._record_mode = value

    @property
    def is_primary(self) -> bool:
        return self._is_primary

    def set_display_fcn(self, display_fcn):
        if self.video_reader is None:
            self._video_reader_thread = QThread()
            self.video_reader = VideoReader(self._video_queue, 1)
            self.video_reader.moveToThread(self._video_reader_thread)
            self._video_reader_thread.started.connect(self.video_reader.process)
            self._video_reader_thread.start()

        self._display_update_fcn = display_fcn

        self.video_reader.image_ready.connect(self.refresh_image)

    def refresh_image(self, data: ndarray):
        if self._frame_count == 0:
            self._start = time.perf_counter()

        self._frame_count += 1

        if self._frame_count % 100 == 0:
            self._fps = self._frame_count / (time.perf_counter() - self._start)

        if self._display_update_fcn is not None:
            self._display_update_fcn(data, self._fps)

    def on_prepare_capture(self, output_location: str):
        if not self._is_enabled:
            return

        if self.video_reader is None:
            self._video_reader_thread = QThread()
            self.video_reader = VideoReader(self._video_queue, 1)
            self.video_reader.moveToThread(self._video_reader_thread)
            self._video_reader_thread.started.connect(self.video_reader.process)
            self._video_reader_thread.start()

        self._frame_count = 0

        if self._camera_source is not None:
            url = self._camera_source + f"&name={self._name}"
            record_properties = VideoRecordProperties(self.record_mode, output_location, 60)
            self._video_capture = VideoCapture(self._name, self._video_cmd_message_queue,
                                               self._video_status_message_queue, self._video_queue, self._network_queue,
                                               url, record_properties)
            self._video_capture.start()
            self._video_status_message_queue.get()

            properties = VideoManager.parse_params(url)
            if "primary" in properties and bool(properties["primary"]) is True:
                self._is_primary = True
            else:
                self._is_primary = False

        else:
            self._is_primary = False

    def on_capture_start(self):
        self._video_cmd_message_queue.put(CaptureMessageKind.CAPTURE)

    def on_capture_stop(self):
        if self._video_capture is not None:
            self._video_cmd_message_queue.put(CaptureMessageKind.TERMINATE)
            self._video_status_message_queue.get()
            self._video_capture.terminate()
            self._video_capture = None

    def on_close(self):
        if self._video_capture is not None:
            self._video_capture.terminate()

        if self.video_reader is not None:
            self._video_reader_thread.quit()

    def _on_trigger(self, sink, trigger_id, context):
        if self._video_capture is not None:
            self._video_cmd_message_queue.put(CaptureMessageKind.TRIGGER)
