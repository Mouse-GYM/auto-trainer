from __future__ import annotations

import os
import pathlib
import time
import logging
import typing
from multiprocessing import Queue, Value, Array
from threading import Event

from numpy import ndarray

from autotrainer.core import clear_queue, FixedArrayQueue, FixedArrayMultiQueue, TriggerManager, ObservableObject
from autotrainer.core.project import ProjectInfo
from autotrainer.video import VideoCapture, VideoRecordProperties, VideoRecordMode, VideoManager, \
    VideoReader, CaptureCommandKind, CaptureProcessStatus, CaptureCameraAttrs, CaptureInferenceAttrs, CaptureAttrs

from tools.acquisition.model.user_settings import UserSettings

logger = logging.getLogger(__name__)

CAPTURE_TRIGGER_ID = "CaptureTrigger"


def create_camera_list():
    cameras = list()

    cameras.append(CaptureCameraAttrs(name="Random Image", url="random://0?width=300&height=200"))

    loc = pathlib.Path(__file__).parent.resolve().parents[2].joinpath("cameras.txt")

    if os.path.isfile(loc):
        file = open(loc, "r")
        lines = file.readlines()
        file.close()
        for line in lines:
            parts = line.split(",")
            if len(parts) == 2:
                cameras.append(CaptureCameraAttrs(name=parts[0].strip(), url=parts[1].strip()))

    return cameras


class VideoCaptureModel(ObservableObject):
    def __init__(self, name, user_settings: UserSettings = None, idx: int = 0):
        super().__init__()

        self._name = name
        self._user_settings = user_settings
        self._index = idx

        self._camera_source: CaptureCameraAttrs | None = None
        self._camera_properties = dict()

        self._video_capture = None
        self._video_reader = None
        self._video_reader_reset_event = None
        self._video_reader_stop_event = None

        self._video_command_queue = Queue()
        self._video_status = Value("i", CaptureProcessStatus.UNKNOWN)
        self._video_frame_index = Value("i", 0)
        self._video_image_queue = None
        self._errors = Array("c", bytes(512))
        self._shape = None

        self._is_enabled = True
        self._is_primary = False

        self._record_mode = VideoRecordMode.CONTINUOUS
        self._is_recording_enabled = False
        self._record_rotate_interval = 3600
        self._is_still_capture_enabled = False
        self._still_image_capture_interval = 0.0

        self._display_update_fcn = None

        self._frame_count = 0
        self._start = 0
        self._fps = 0

        self._last_error = None

        self._camera_list = create_camera_list()

        self._is_trace_enabled = True

        TriggerManager.instance().register(self._on_trigger, CAPTURE_TRIGGER_ID)

        self._update_camera_source(self._camera_list[0])

    @property
    def name(self) -> str:
        return self._name

    @property
    def camera_list(self) -> typing.List[CaptureCameraAttrs]:
        return self._camera_list

    @property
    def camera_source(self) -> CaptureCameraAttrs:
        return self._camera_source

    @camera_source.setter
    def camera_source(self, value: CaptureCameraAttrs):
        if self._camera_source == value:
            return

        old_value = self._camera_source

        self._update_camera_source(value)

        self.property_changed("camera", value, old_value)

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value: bool):
        self._is_enabled = self._on_property_changed("is_enabled", value, self._is_enabled)

    @property
    def is_recording_enabled(self) -> bool:
        return self._is_recording_enabled

    @is_recording_enabled.setter
    def is_recording_enabled(self, value: bool):
        self._is_recording_enabled = self._on_property_changed("is_recording_enabled", value,
                                                               self._is_recording_enabled)

    @property
    def record_mode(self) -> VideoRecordMode:
        return self._record_mode

    @record_mode.setter
    def record_mode(self, value: VideoRecordMode):
        self._record_mode = self._on_property_changed("record_mode", value, self._record_mode)

    @property
    def is_still_capture_enabled(self) -> bool:
        return self._is_still_capture_enabled

    @is_still_capture_enabled.setter
    def is_still_capture_enabled(self, value: bool):
        self._is_still_capture_enabled = self._on_property_changed("is_still_capture_enabled", value,
                                                                   self._is_still_capture_enabled)

    @property
    def still_image_capture_interval(self) -> float:
        return self._still_image_capture_interval

    @still_image_capture_interval.setter
    def still_image_capture_interval(self, value: float):
        self._still_image_capture_interval = self._on_property_changed("still_image_capture_interval", value,
                                                                       self._still_image_capture_interval)

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

        return 0, 0

    @shape.setter
    def shape(self, value):
        self._shape = self._on_property_changed("shape", value, self._shape)

    @property
    def last_error(self) -> str:
        return self._last_error

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

        if self._frame_count % 1500 == 0:
            self._fps = 1e9 * self._frame_count / (time.perf_counter_ns() - self._start)
            self._trace(f"display fps: {int(self._fps)}")

        if self._display_update_fcn is not None and self._video_capture is not None:
            self._display_update_fcn(data, self._fps)

    def on_prepare_capture(self, project_info: ProjectInfo, network_queue: FixedArrayMultiQueue = None) -> bool:
        self._last_error = None

        if not self._is_enabled:
            return True

        self._frame_count = 0

        self._video_reader_initialize()

        if self._camera_source is not None:
            if "?" in self._camera_source.url:
                url = self._camera_source.url + f"&name={self._name}"
            else:
                url = self._camera_source.url + f"?name={self._name}"

            camera = CaptureCameraAttrs(name=self._name, url=url)

            inference = CaptureInferenceAttrs(queue=network_queue, index=self._index)

            capture_attrs = CaptureAttrs(command_queue=self._video_command_queue, status=self._video_status,
                                         image_queue=self._video_image_queue, frame=self._video_frame_index,
                                         camera=camera, inference=inference, errors=self._errors)

            rotate_interval = self._record_rotate_interval if self._is_recording_enabled else -1
            image_interval = self._still_image_capture_interval if self._is_still_capture_enabled else 0
            record_properties = VideoRecordProperties(project_info=project_info, record_mode=self.record_mode,
                                                      video_rotate_interval=rotate_interval,
                                                      image_interval=image_interval)

            self._video_capture = VideoCapture(capture_attrs, record_properties)

            self._video_capture.start()

            logger.debug(f"<{self._name}> waiting for start acknowledgement")

            if not self._wait_for_capture_status(CaptureProcessStatus.RUNNING, 5):
                logger.error(f"<{self._name}> failed to receive start acknowledgement")
                self._last_error = self._errors.value.decode()
                self._video_capture.terminate()
                self._video_capture = None
                return False

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

        self._send_command(CaptureCommandKind.ENABLE_CAPTURE)

    def on_capture_notify_end(self):
        self._send_command(CaptureCommandKind.DISABLE_CAPTURE)

    def on_capture_stop(self):
        if not self._is_enabled:
            return

        self._video_reader_teardown()

        if self._video_capture is not None:
            self._send_command(CaptureCommandKind.TERMINATE)

            if self._wait_for_capture_status(CaptureProcessStatus.TERMINATED, 5):
                logger.debug(f"<{self._name}> video capture terminate acknowledged")
            else:
                logger.error(f"<{self._name}> did not receive process terminates status")

        if self._video_command_queue.qsize() > 0:
            self._trace(f"clearing command queue {self._video_command_queue.qsize()}")
        clear_queue(self._video_command_queue)

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

    def load_configuration(self, conf):
        if "id" in conf:
            self._name = conf["id"]
        if "isEnabled" in conf:
            self.is_enabled = conf["isEnabled"]
        if "isRecordEnabled" in conf:
            self.is_recording_enabled = conf["isRecordEnabled"]
        if "recordMode" in conf:
            self.record_mode = VideoRecordMode(conf["recordMode"])
        if "isStillImageCaptureEnabled" in conf:
            self.is_still_capture_enabled = conf["isStillImageCaptureEnabled"]
        if "stillImageCaptureInterval" in conf:
            self.still_image_capture_interval = conf["stillImageCaptureInterval"]

        if "url" in conf:
            if "name" in conf:
                name = conf["name"]
            else:
                name = "<unnamed>"

            url = conf["url"]

            existing = list(filter(lambda m: m.url == url, self._camera_list))

            if len(existing) == 0:
                source = CaptureCameraAttrs(name=name, url=url)
                self._camera_list.insert(0, source)
            else:
                source = existing[0]

            self.camera_source = source

    def write_configuration(self):
        return {"id": self._name, "name": self._camera_source.name, "url": self._camera_source.url,
                "isEnabled": self._is_enabled, "isRecordEnabled": self._is_recording_enabled,
                "recordMode": int(self._record_mode), "isStillImageCaptureEnabled": self._is_still_capture_enabled,
                "stillImageCaptureInterval": self._still_image_capture_interval}

    def _wait_for_capture_status(self, expected: CaptureProcessStatus, timeout: int):
        start_ns = time.perf_counter_ns()
        elapsed = 0

        while self._video_status.value != expected and elapsed < timeout:
            time.sleep(0.001)
            elapsed = (time.perf_counter_ns() - start_ns) / 1e9

        return elapsed <= timeout

    def _on_trigger(self, _sink, _trigger_id, context):
        if self._video_capture is not None:
            if context:
                self._send_command(CaptureCommandKind.ENABLE_RECORDING)
            else:
                self._send_command(CaptureCommandKind.DISABLE_RECORDING)

    def _update_camera_source(self, cam: CaptureCameraAttrs):
        if cam is None or len(cam.url) == 0:
            self._camera_source = None
            self._camera_properties = dict()
            self._video_image_queue = None
            return

        value = cam.url

        if "&name" not in value:
            if "?" in value:
                value = value + f"&name={self._name}"
            else:
                value = value + f"?name={self._name}"

        properties = VideoManager.parse_params(value)

        self.shape = None

        if "height" in properties and "width" in properties:
            width = int(properties["height"])
            height = int(properties["width"])
            if width > 0 and height > 0:
                self.shape = (width, height)
        else:
            self.shape = (300, 200)

        self._video_image_queue = None if self._shape is None else FixedArrayQueue(3, self._shape)

        self._camera_source = cam

        self._camera_properties = properties

        self._trace(str(self._camera_properties))

    def _video_reader_initialize(self):
        if self._video_reader is None and self._display_update_fcn is not None:
            self._video_reader_stop_event = Event()
            self._video_reader_reset_event = Event()
            self._video_reader = VideoReader(self._name, self._video_image_queue, self.refresh_image,
                                             self._video_reader_stop_event)
            self._video_reader.start()

    def _video_reader_teardown(self):
        if self._video_reader is not None:
            self._video_reader_stop_event.set()
            self._video_reader.join()
            self._video_reader = None

    def _send_command(self, cmd: CaptureCommandKind, context: object = None):
        if self._video_command_queue is not None:
            self._video_command_queue.put((cmd, context))

    def _trace(self, message: str):
        if self._is_trace_enabled:
            logger.debug(f"<{self._name}> {message}")
