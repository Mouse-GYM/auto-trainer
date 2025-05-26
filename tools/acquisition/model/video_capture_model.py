import multiprocessing
import os
import pathlib
import time
import logging
from multiprocessing.context import BaseContext
from typing import Optional, List
from multiprocessing import Queue, Value, Array
from threading import Event
import urllib
from urllib.parse import urlparse

import numpy
from numpy import ndarray

from autotrainer.core import clear_queue, FixedArrayQueue, FixedArrayMultiQueue, ObservableObject, \
    CameraConfiguration, CameraId, NotificationCenter, TriggerNotification, Notification
from autotrainer.core.multiproc import get_mp_ctx
from autotrainer.core.project import ProjectInfo
from autotrainer.video import VideoCapture, VideoRecordProperties, VideoRecordMode, VideoManager, \
    VideoReader, CaptureCommandKind, CaptureProcessStatus, CaptureCameraAttrs, CaptureInferenceAttrs, CaptureAttrs
from tools.acquisition.model.project_dependent_protocol import ProjectDependentProtol

from tools.acquisition.model.user_preferences import UserPreferences

logger = logging.getLogger(__name__)


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


class VideoCaptureModel(ObservableObject, ProjectDependentProtol):
    def __init__(self, name, preferences: UserPreferences = None, inference_index: int = -1,
                 *,
                 mp_ctx: Optional[BaseContext] = None,
    ):
        super().__init__()

        if mp_ctx is None:
            mp_ctx = get_mp_ctx()

        self._id = CameraId.Left

        self._name = name
        self._preferences = preferences
        self._inference_index = inference_index

        self._camera_source: Optional[CaptureCameraAttrs] = None
        self._camera_properties = {}

        self._video_capture: Optional[VideoCapture] = None
        self._video_reader = None
        self._video_reader_reset_event = None
        self._video_reader_stop_event = None

        self._video_command_queue = mp_ctx.Queue(maxsize=64)
        self._video_status = mp_ctx.Value("i", CaptureProcessStatus.UNKNOWN)
        self._video_frame_index = mp_ctx.Value("i", 0)
        self._video_image_queue: Optional[FixedArrayQueue] = None
        self._errors = mp_ctx.Array("c", bytes(512))
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

        self._project: Optional[ProjectInfo] = None

        NotificationCenter.default_center().add_observer(TriggerNotification.CAPTURE_ID, self._on_trigger)

        self._update_camera_source(self._camera_list[0])

    @property
    def project(self) -> ProjectInfo:
        return self._project

    @project.setter
    def project(self, value: ProjectInfo):
        self._project = value

    @property
    def name(self) -> str:
        return self._name

    @property
    def camera_list(self) -> List[CaptureCameraAttrs]:
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
        """
        Be aware this is the shape as seen by the cameras ndarray frames which is row x col not width x height.
        """
        if "height" in self._camera_properties and "width" in self._camera_properties:
            rows = int(self._camera_properties["height"])
            cols = int(self._camera_properties["width"])
            if rows > 0 and cols > 0:
                return rows, cols

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

    def on_prepare_capture(self, network_queue: Optional[FixedArrayMultiQueue] = None) -> bool:
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

            inference = CaptureInferenceAttrs(queue=network_queue, index=self._inference_index)

            capture_attrs = CaptureAttrs(
                command_queue=self._video_command_queue,
                status=self._video_status,
                image_queue=self._video_image_queue,
                fps_image_queue=15 if self._preferences is None else self._preferences.live_feed_refresh_rate,
                frame=self._video_frame_index,
                camera=camera,
                inference=inference,
                errors=self._errors,
            )

            rotate_interval = self._record_rotate_interval if self._is_recording_enabled else -1
            image_interval = self._still_image_capture_interval if self._is_still_capture_enabled else 0
            record_properties = VideoRecordProperties(project_info=self._project, record_mode=self.record_mode,
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

        else:
            self._is_primary = False

        return True

    def on_capture_start(self):
        if not self._is_enabled:
            logger.warning("%s: on_capture_start called but disabled", self)
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

        if self._video_capture is not None:
            self._trace("waiting for process termination")
            while self._video_capture.is_alive():
                time.sleep(0.1)
            self._trace("process terminated")
            self._video_capture.join()
            self._video_capture = None

        # NB: clearing video cmd queue having waited & joined the capture process is best.
        clear_queue(self._video_command_queue)
        # clear_queue(self._video_image_queue)
        # video_image_queue is our FixedArrayQueue which cannot be "cleared" by another thread than the
        # one consuming it. We anyway recreate a new one for each new capture.


    def on_close(self):
        if self._video_capture is not None:
            self._video_capture.terminate()
            self._video_capture.join()
        self._video_reader_teardown()

    def load_configuration(self, conf: CameraConfiguration):
        self._id = conf.id
        self._name = str(conf.id)
        self.is_enabled = conf.is_enabled
        self.is_recording_enabled = conf.is_record_enabled
        self.record_mode = VideoRecordMode(conf.record_mode)
        self.is_still_capture_enabled = conf.is_still_image_capture_enabled
        self.still_image_capture_interval = conf.still_image_capture_interval

        url = f"{conf.scheme}://{conf.host}"

        if conf.port > 0:
            url += f":{conf.port}"

        if len(conf.path) > 0:
            url += f"/{conf.path}"

        if len(conf.params) > 0:
            url += "?" + urllib.parse.urlencode(conf.params)

        existing = list(filter(lambda m: m.url == url, self._camera_list))

        name = self._name or "<unnamed>"

        if len(existing) == 0:
            non_duplicate = name
            idx = 1
            same_name = list(filter(lambda m: m.name == non_duplicate, self._camera_list))
            while len(same_name) > 0:
                non_duplicate = f"{name} ({idx})"
                same_name = list(filter(lambda m: m.name == non_duplicate, self._camera_list))
                idx += 1
            source = CaptureCameraAttrs(name=non_duplicate, url=url)
            self._camera_list.insert(0, source)
            self.property_changed("camera_list", self._camera_list, self._camera_list)
        else:
            source = existing[0]

        self.camera_source = source

    def save_configuration(self) -> CameraConfiguration:
        parsed = urlparse(self._camera_source.url)

        params = VideoManager.parse_params(self._camera_source.url)

        for key in params:
            try:
                val = float(params[key])
                if abs(int(val) - val) < 2.0 * float(numpy.finfo(float).eps):
                    val = int(val)
                params[key] = val
            except (ValueError, TypeError):
                if str(params[key]).lower() == "true":
                    params[key] = True
                elif str(params[key]).lower() == "false":
                    params[key] = False

        return CameraConfiguration(id=self._id, name=self._name, is_enabled=self._is_enabled,
                                   is_record_enabled=self._is_recording_enabled,
                                   record_mode=self._record_mode.value,
                                   is_still_image_capture_enabled=self._is_still_capture_enabled,
                                   still_image_capture_interval=self.still_image_capture_interval,
                                   scheme=parsed.scheme, host=parsed.hostname, port=parsed.port or 0, path=parsed.path,
                                   params=params)

    def _wait_for_capture_status(self, expected: CaptureProcessStatus, timeout: int):
        start_ns = time.perf_counter_ns()
        elapsed = 0

        while self._video_status.value != expected and elapsed < timeout:
            time.sleep(0.001)
            elapsed = (time.perf_counter_ns() - start_ns) / 1e9

        return elapsed <= timeout

    def _on_trigger(self, notification: Notification):
        if self._video_capture is not None:
            if notification.context:
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

        self._video_image_queue = None if self._shape is None else FixedArrayQueue(
            3,
            self._shape,
            name="video_q",
            mp_ctx=get_mp_ctx(),
        )

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
        else:
            logger.warning("%s: _send_command: %s but video command queue is None", self, cmd)

    def _trace(self, message: str):
        if self._is_trace_enabled:
            logger.debug(f"<{self._name}> {message}")
