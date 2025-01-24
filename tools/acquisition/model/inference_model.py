import logging
import os
import queue
import time
import typing
from typing import Optional
from dataclasses import dataclass
from enum import Enum
from multiprocessing import Queue
from threading import Thread

import cv2
import numpy

from autotrainer.behavior import SegmentationConfiguration, DetectionConfiguration, intersession_inference, \
    intersession_process
from autotrainer.behavior.behavior_event_kind import BehaviorEventKind
from autotrainer.core import FixedArrayMultiQueue, ObservableObject, ProjectInfo, EventManager, clear_queue
from autotrainer.core.fixed_array_queue import BufferResult
from autotrainer.inference import PoseProcess, InferenceCommandMessageKind, InferenceStatusMessageKind, PoseAlgorithm, \
    DlcPoseModel, MemoryPoseModel, InferenceMode

logger = logging.getLogger(__name__)


class InferenceStatus(str, Enum):
    stopped = "Stopped",
    loading = "Loading",
    waiting = "Waiting",
    live = "Live",
    intersession = "Intersession",
    stopping = "Stopping"


@dataclass
class IntersessionBlock:
    configuration: SegmentationConfiguration
    frame_count: int = 0
    parts_count: int = 10
    pose_data: numpy.ndarray = None

    def __post_init__(self):
        self.pose_data = numpy.empty((0, self.parts_count * 3), dtype=numpy.float32)


@dataclass
class IntersessionDetection:
    configuration: DetectionConfiguration


class InferenceModel(ObservableObject):
    def __init__(self, pose_algorithm: PoseAlgorithm):
        super().__init__(event_names=("pose_response_ready",))

        self._data_queue = Queue()
        self._cmd_queue = Queue()
        self._msg_queue = Queue()

        self._offline_queue: Optional[FixedArrayMultiQueue] = None

        self._offline_thread = None

        self._is_enabled = False
        self._model_location = ""
        self._algorithm = pose_algorithm

        self._msg_thread = None
        self._data_thread = None

        self._process = None

        self._is_running = True

        self._is_predict_enabled = True

        self._status = InferenceStatus.stopped

        self._frames_per_camera = 0
        self._frame_width = 1
        self._frame_height = 1

        self._intersession_wait_time: float = 1.0

        self._project: Optional[ProjectInfo] = None

        self._intersession_block: Optional[IntersessionBlock] = None

        self._intersession_detection: Optional[IntersessionDetection] = None

    @property
    def project(self) -> ProjectInfo:
        return self._project

    @project.setter
    def project(self, value: ProjectInfo) -> None:
        self._project = value

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value: bool):
        self._is_enabled = self._on_property_changed("is_enabled", value, self._is_enabled)

    @property
    def is_predict_enabled(self) -> bool:
        return self._is_predict_enabled

    @is_predict_enabled.setter
    def is_predict_enabled(self, value: bool):
        self._is_predict_enabled = self._on_property_changed("is_predict_enabled", value, self._is_predict_enabled)

    @property
    def model_location(self) -> str:
        return self._model_location

    @model_location.setter
    def model_location(self, value: str):
        self._model_location = self._on_property_changed("model_location", value, self._model_location)

    @property
    def intersession_wait_time(self) -> float:
        return self._intersession_wait_time

    @intersession_wait_time.setter
    def intersession_wait_time(self, value: float):
        self._intersession_wait_time = self._on_property_changed("intersession_wait_time", value,
                                                                 self._intersession_wait_time)

    @property
    def status(self) -> InferenceStatus:
        return self._status

    @property
    def pose_algorithm(self) -> PoseAlgorithm:
        return self._algorithm

    def perform_segmentation(self, configuration: SegmentationConfiguration):
        logger.info("performing segmentation")
        self._intersession_block = IntersessionBlock(configuration=configuration, parts_count=self._algorithm.part_count)
        self._send_message(InferenceCommandMessageKind.ProcessOffline)
        self._offline_thread = Thread(target=self._feed_intersession_analysis)
        self._offline_thread.start()

    def perform_detection(self, configuration: DetectionConfiguration):
        logger.info("performing detection analysis")
        self._intersession_detection = IntersessionDetection(configuration)
        self._offline_thread = Thread(target=self._intersession_process)
        self._offline_thread.start()

    def perform_live(self):
        pass

    def start(self, network_queue: FixedArrayMultiQueue) -> bool:
        if self._msg_thread is None:
            self._msg_thread = Thread(target=self._monitor_msg_queue)
            self._msg_thread.start()

        if self._data_thread is None:
            self._data_thread = Thread(target=self._monitor_data_queue)
            self._data_thread.start()

        if network_queue is None:
            logger.warning("pellet not started because there is no pellet image queue")
            self._set_status(InferenceStatus.stopped)
            return False

        self._frame_height, self._frame_width = network_queue.shape

        self._frames_per_camera = network_queue.frames_per_camera

        self._offline_queue = FixedArrayMultiQueue(3, network_queue.camera_count,
                                                   network_queue.frames_per_camera, network_queue.shape)

        if self._model_location is None or len(self._model_location) == 0:
            logger.warning("pellet model not specified; using in-memory random data")
            model = MemoryPoseModel(network_queue.batch_size)
        else:
            model = DlcPoseModel(self._model_location, 1, 0, network_queue.batch_size)

        if not model.is_valid():
            logger.warning("pellet not started because the model does not exist at the specified location")
            return False

        self._process = PoseProcess(model, network_queue, self._offline_queue, self._data_queue, self._cmd_queue,
                                    self._msg_queue)

        self._process.start()

    def stop(self):
        if self._process is not None:
            self._set_status(InferenceStatus.stopping)

            self._send_message(InferenceCommandMessageKind.Terminate)

            logger.debug(f"<pellet> waiting for process termination")

            while self._process.is_alive():
                time.sleep(0.1)

            logger.debug(f"<pellet> process terminated")

            self._process = None

            self._set_status(InferenceStatus.stopped)

            clear_queue(self._data_queue)
            clear_queue(self._msg_queue)
            clear_queue(self._cmd_queue)

    def terminate(self):
        self.stop()

        self._is_running = False

    def load_configuration(self, configuration: dict):
        if "model" in configuration:
            self.model_location = configuration["model"]
        if "isEnabled" in configuration:
            self.is_enabled = configuration["isEnabled"]
        if "intersessionWaitTime" in configuration:
            self.intersession_wait_time = configuration["intersessionWaitTime"]

    def save_configuration(self) -> dict:
        return {"model": self.model_location, "isEnabled": self._is_enabled,
                "intersessionWaitTime": self._intersession_wait_time}

    def _set_status(self, status: InferenceStatus):
        self._status = self._on_property_changed("status", status, self._status)

    def _send_message(self, kind: InferenceCommandMessageKind, context: typing.Any = None):
        self._cmd_queue.put((kind, context))

    def _monitor_msg_queue(self):
        while self._is_running:
            try:
                msg, context = self._msg_queue.get(block=False, timeout=0.5)
                if msg == InferenceStatusMessageKind.Initialized:
                    logger.info(msg)
                    self._set_status(InferenceStatus.waiting)
                    self._algorithm.initialize(context)
                    self._send_message(InferenceCommandMessageKind.Start)
                elif msg == InferenceStatusMessageKind.Loading:
                    self._set_status(InferenceStatus.loading)
                elif msg == InferenceStatusMessageKind.Performance:
                    logger.info(f"{context :.1f} predict calls/s")
                    fps = context * self._frames_per_camera
                    logger.info(f"{fps :.1f} frames/camera/s ({(fps * 2):.1f} total frames/s)")
                elif msg == InferenceStatusMessageKind.Running:
                    mode = InferenceMode(context)
                    logger.info(f"predict running with {mode.name} queue")
                    if mode == InferenceMode.Live:
                        self._set_status(InferenceStatus.live)
                    else:
                        self._set_status(InferenceStatus.intersession)
            except queue.Empty:
                time.sleep(0.001)
            except Exception as ex:
                logger.error(ex)
                print(ex)

    def _monitor_data_queue(self):
        while self._is_running:
            try:
                (pose_data, mode) = self._data_queue.get(block=False, timeout=0.5)
                if mode == InferenceMode.Live:
                    # Normalize locations.  Not all consumers will be scaling the location by the original frame size.
                    for frame in pose_data:
                        frame[:, 0] /= self._frame_width
                        frame[:, 1] /= self._frame_height
                    response = self._algorithm.process(pose_data)
                    self.pose_response_ready(response)
                else:
                    if pose_data is None:
                        if self._intersession_block is not None:
                            success = True

                            try:
                                logger.info(f"processed {self._intersession_block.pose_data.shape[0]} pose responses")

                                intersession_inference(self._intersession_block.pose_data, self._algorithm.part_names,
                                                       self._project)
                            except Exception as ex:
                                logger.error(ex)
                                success = False

                            self._intersession_block.configuration.complete(
                                self._intersession_block.configuration.nonce, success)
                            self._intersession_block = None
                    else:
                        for frame in pose_data:
                            self._intersession_block.pose_data = numpy.vstack(
                                [self._intersession_block.pose_data, frame.flatten()])
            except queue.Empty:
                time.sleep(0.001)
            except Exception as ex:
                logger.error(ex)

    def _feed_intersession_analysis(self):
        try:
            path_1 = self._project.get_video_path(name=self._project.camera_1, allow_overwrite=True)[0]
            file_size = os.path.getsize(path_1)
            logger.info(f"{path_1} size: {file_size}")

            path_2 = self._project.get_video_path(name=self._project.camera_2, allow_overwrite=True)[0]
            file_size = os.path.getsize(path_2)
            logger.info(f"{path_2} size: {file_size}")

            capture_1 = None
            capture_2 = None

            def check_frame_count(file_path: str):
                capture = cv2.VideoCapture(file_path)
                count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
                if count < 1:
                    capture.release()
                    return None
                return capture

            timeout = time.time() + self._intersession_wait_time

            while capture_1 is None or capture_2 is None:
                if capture_1 is None:
                    capture_1 = check_frame_count(path_1)
                if capture_2 is None:
                    capture_2 = check_frame_count(path_2)
                if time.time() > timeout:
                    EventManager.post_event(BehaviorEventKind.intersessionSegmentationInputError)
                    logger.error("timeout waiting for intersession video files")
                    break

            idx = 0

            while True:
                if not self._put_intersession_frame(capture_1, 0):
                    break
                if not self._put_intersession_frame(capture_2, 1):
                    break
                idx += 1

            logger.info(f"passed {idx} frames per camera")

            self._intersession_block.frame_count = idx

            self._send_message(InferenceCommandMessageKind.ProcessLiveWhenReady)
        except Exception as ex:
            logger.error(ex)
            EventManager.post_event(BehaviorEventKind.intersessionSegmentationError, context=str(ex))
            self._send_message(InferenceCommandMessageKind.ProcessLiveWhenReady)
            self._intersession_block.configuration.complete(self._intersession_block.configuration.nonce, False)
            self._intersession_block = None

    def _put_intersession_frame(self, capture, index: int) -> bool:
        ret, frame = capture.read()

        if not ret:
            logger.info(f"end of video at index {index}")
            return False

        while True:
            if len(numpy.shape(frame)) < 3:
                buffer_result = self._offline_queue.put(frame, index, False)
            else:
                buffer_result = self._offline_queue.put(frame[:, :, 0], index, False)

            if buffer_result == BufferResult.Overflow:
                time.sleep(0.01)
            else:
                break

        return True

    def _intersession_process(self):
        try:
            intersession_process(self._project)
            self._intersession_detection.configuration.complete(self._intersession_detection.configuration.nonce, True)
        except Exception as ex:
            logger.error(ex)
            self._intersession_detection.configuration.complete(self._intersession_detection.configuration.nonce, False)

        self._intersession_block = None
