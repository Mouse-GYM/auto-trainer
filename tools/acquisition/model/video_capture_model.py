import time
import logging
from multiprocessing import Queue
from threading import Event

from numpy import ndarray

from autotrainer.core import clear_queue, FixedArrayQueue, FixedArrayMultiQueue
from autotrainer.video import VideoCapture, CaptureMessageKind, VideoRecordProperties, VideoRecordMode, VideoManager, \
    VideoReader, TriggerManager

from tools.acquisition.model.user_settings import UserSettings

logger = logging.getLogger(__name__)

CAPTURE_TRIGGER_ID = "CaptureTrigger"


class VideoCaptureModel:
    def __init__(self, name, user_settings: UserSettings = None, idx: int = 0):
        super().__init__()

        self._name = name
        self._user_settings = user_settings
        self._index = idx

        self._camera_source = None
        self._camera_properties = dict()

        self._video_capture = None
        self._video_reader = None
        self._video_reader_reset_event = None
        self._video_reader_stop_event = None

        self._video_cmd_message_queue = Queue()
        self._video_status_message_queue = Queue()
        self._video_queue = None
        self._shape = None

        self._is_enabled = True
        self._is_primary = False
        self._record_mode = VideoRecordMode.NONE
        self._is_recording_enabled = False

        self._display_update_fcn = None

        self._frame_count = 0
        self._start = 0
        self._fps = 0

        self._is_trace_enabled = True

        TriggerManager.instance().register(self._on_trigger, CAPTURE_TRIGGER_ID)

    @property
    def camera_source(self) -> str:
        return self._camera_source

    @camera_source.setter
    def camera_source(self, value: str):
        if value != self._camera_source:
            self._update_camera_source(value)

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

    @property
    def shape(self) -> (int, int):
        if "height" in self._camera_properties and "width" in self._camera_properties:
            width = int(self._camera_properties["height"])
            height = int(self._camera_properties["width"])
            if width > 0 and height > 0:
                return width, height

    @property
    def is_trace_enabled(self) -> bool:
        return self._is_trace_enabled

    @is_trace_enabled.setter
    def is_trace_enabled(self, value: bool):
        self._is_trace_enabled = value

    def set_display_fcn(self, display_fcn):
        self._display_update_fcn = display_fcn

    def refresh_image(self, data: ndarray):
        if self._frame_count == 0:
            self._start = time.perf_counter_ns()

        self._frame_count += 1

        if self._frame_count % 150 == 0:
            self._fps = 1e9 * self._frame_count / (time.perf_counter_ns() - self._start)
            self._trace(f"display fps: {int(self._fps)}")

        if self._display_update_fcn is not None and self._video_capture is not None:
            self._display_update_fcn(data, self._fps)

    def on_prepare_capture(self, output_location: str, network_queue: FixedArrayMultiQueue = None) -> bool:
        if not self._is_enabled:
            return True

        self._frame_count = 0

        self._video_reader_initialize()

        if self._camera_source is not None:
            if "?" in self._camera_source:
                url = self._camera_source + f"&name={self._name}"
            else:
                url = self._camera_source + f"?name={self._name}"

            record_properties = VideoRecordProperties(self.record_mode, output_location, 3600)

            self._video_capture = VideoCapture(self._name, self._video_cmd_message_queue,
                                               self._video_status_message_queue, self._video_queue,
                                               network_queue, url, self._index, record_properties)

            self._video_capture.start()

            logger.info(f"<{self._name}> waiting for start acknowledgement")

            try:
                message = self._video_status_message_queue.get(timeout=10)
            except:
                logger.error(f"<{self._name}> failed to receive start acknowledgement")
                self._video_capture.terminate()
                self._video_capture = None
                return False

            if message == CaptureMessageKind.BEGIN_CAPTURE_ACKNOWLEDGE:
                logger.info(f"<{self._name}> video capture start acknowledged")
            else:
                logger.error(f"<{self._name}> unexpected start response")

            properties = VideoManager.parse_params(url)

            if "primary" in properties and bool(properties["primary"]) is True:
                self._is_primary = True
            else:
                self._is_primary = False

            decimation = 1 if self._user_settings is None else self._user_settings.live_feed_refresh_rate

            if self._index == -1:
                if "fps" in properties:
                    self._video_reader.decimation = max(int(int(properties["fps"]) / decimation), 1)
                elif self._video_reader is not None:
                    # Assume 30fps
                    self._video_reader.decimation = max(int(30 / decimation), 1)
            else:
                self._video_reader.decimation = 1
        else:
            self._is_primary = False

        return True

    def on_capture_start(self):
        if not self._is_enabled:
            return

        self._video_cmd_message_queue.put(CaptureMessageKind.BEGIN_CAPTURE)

    def on_capture_notify_end(self):
        self._video_cmd_message_queue.put(CaptureMessageKind.END_CAPTURE)

    def on_capture_stop(self):
        if not self._is_enabled:
            return

        self._video_reader_teardown()

        if self._video_capture is not None:
            self._video_cmd_message_queue.put(CaptureMessageKind.TERMINATE)

            message = self._video_status_message_queue.get()

            if message == CaptureMessageKind.TERMINATED:
                logger.info(f"<{self._name}> video capture terminate acknowledged")
            else:
                logger.error(f"<{self._name}> unexpected terminate response")

        if self._video_cmd_message_queue.qsize() > 0:
            self._trace(f"clearing command queue {self._video_cmd_message_queue.qsize()}")
        clear_queue(self._video_cmd_message_queue)
        if self._video_status_message_queue.qsize() > 0:
            self._trace(f"clearing status queue {self._video_status_message_queue.qsize()}")
        clear_queue(self._video_status_message_queue)

        if self._video_capture is not None:
            self._trace("waiting for process termination")

            while self._video_capture.is_alive():
                time.sleep(0.1)

            self._trace("process terminated")

            self._video_capture = None

    def on_close(self):
        if self._video_capture is not None:
            self._video_capture.terminate()

        self._video_reader_teardown()

    def _on_trigger(self, sink, trigger_id, context):
        if self._video_capture is not None:
            self._video_cmd_message_queue.put(CaptureMessageKind.TRIGGER)

    def _update_camera_source(self, value: str):
        if value is None or len(value) == 0:
            self._camera_source = None
            self._camera_properties = dict()
            self._video_queue = None
            return

        if "&name" not in value:
            if "?" in value:
                value = value + f"&name={self._name}"
            else:
                value = value + f"?name={self._name}"

        properties = VideoManager.parse_params(value)

        self._shape = None

        if "height" in properties and "width" in properties:
            width = int(properties["height"])
            height = int(properties["width"])
            if width > 0 and height > 0:
                self._shape = (width, height)

        self._video_queue = None if self._shape is None else FixedArrayQueue(3, self._shape)

        self._camera_source = value

        self._camera_properties = properties

        self._trace(str(self._camera_properties))

    def _video_reader_initialize(self):
        if self._video_reader is None and self._display_update_fcn is not None:
            self._video_reader_stop_event = Event()
            self._video_reader_reset_event = Event()
            self._video_reader = VideoReader(self._name, self._video_queue, self.refresh_image,
                                             self._video_reader_stop_event)
            self._video_reader.start()

    def _video_reader_teardown(self):
        if self._video_reader is not None:
            self._video_reader_stop_event.set()
            self._video_reader.join()
            self._video_reader = None

    def _trace(self, message: str):
        if self._is_trace_enabled:
            logger.debug(f"<{self._name}> {message}")
