from __future__ import annotations

import logging
import queue
import time
import typing
from multiprocessing import Queue
from threading import Thread

from autotrainer.core import FixedArrayMultiQueue, ObservableObject
from autotrainer.inference import PosePredict, AnalysisCommandMessageKind, AnalysisStatusMessageKind, PoseAlgorithm, \
    DlcPoseModel, MemoryPoseModel, AnalysisMode

logger = logging.getLogger(__name__)


class AnalysisModel(ObservableObject):
    def __init__(self, pose_algorithm: PoseAlgorithm):
        super().__init__(event_names=("pose_response_ready",))

        self._data_queue = Queue()
        self._cmd_queue = Queue()
        self._msg_queue = Queue()

        self._offline_queue: Queue | FixedArrayMultiQueue | None = None

        self._is_enabled = False
        self._model_location = ""
        self._algorithm = pose_algorithm

        self._msg_thread = None
        self._data_thread = None

        self._process = None

        self._is_running = True

        self._is_predict_enabled = True

        self._frames_per_camera = 0

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

    def start(self, network_queue: FixedArrayMultiQueue) -> bool:
        if self._msg_thread is None:
            self._msg_thread = Thread(target=self._monitor_msg_queue)
            self._msg_thread.start()

        if self._data_thread is None:
            self._data_thread = Thread(target=self._monitor_data_queue)
            self._data_thread.start()

        if network_queue is None:
            logger.warning("analysis not started because there is no inference image queue")
            return False

        self._offline_queue = FixedArrayMultiQueue(network_queue.depth, network_queue.camera_count,
                                                   network_queue.frames_per_camera, network_queue.shape)

        self._frames_per_camera = network_queue.frames_per_camera

        if self._model_location is None or len(self._model_location) == 0:
            logger.warning("analysis model not specified; using in-memory random data")
            model = MemoryPoseModel(network_queue.batch_size)
        else:
            model = DlcPoseModel(self._model_location, 1, 0, network_queue.batch_size)

        if not model.is_valid():
            logger.warning("analysis not started because the model does not exist at the specified location")
            return False

        self._process = PosePredict(model, network_queue, self._offline_queue, self._data_queue, self._cmd_queue,
                                    self._msg_queue)

        self._process.start()

    def stop(self):
        if self._process is not None:
            self._send_message(AnalysisCommandMessageKind.Terminate)

            logger.debug(f"<analysis> waiting for process termination")

            while self._process.is_alive():
                time.sleep(0.1)

            logger.debug(f"<analysis> process terminated")

            self._process = None

    def terminate(self):
        self.stop()

        self._is_running = False

    def load_configuration(self, conf):
        if "model" in conf:
            self.model_location = conf["model"]
        if "isEnabled" in conf:
            self.is_enabled = conf["isEnabled"]

    def write_configuration(self):
        return {"model": self.model_location, "isEnabled": self._is_enabled}

    def _send_message(self, kind: AnalysisCommandMessageKind, context: typing.Any = None):
        self._cmd_queue.put((kind, context))

    def _monitor_msg_queue(self):
        while self._is_running:
            try:
                msg, context = self._msg_queue.get(block=False, timeout=0.5)
                if msg == AnalysisStatusMessageKind.Initialized:
                    logger.info(msg)
                    self._algorithm.initialize(context)
                    self._send_message(AnalysisCommandMessageKind.Start)
                elif msg == AnalysisStatusMessageKind.Performance:
                    logger.info(f"{context :.1f} predict calls/s")
                    fps = context * self._frames_per_camera
                    logger.info(f"{fps :.1f} frames/camera/s ({(fps * 2):.1f} total frames/s)")
                elif msg == AnalysisStatusMessageKind.Running:
                    logger.info(f"predict running with {AnalysisMode(context).name} queue")
            except queue.Empty:
                time.sleep(0.001)
            except Exception as ex:
                logger.error(ex)

    def _monitor_data_queue(self):
        while self._is_running:
            try:
                pose_data = self._data_queue.get(block=False, timeout=0.5)
                response = self._algorithm.process(pose_data)
                self.pose_response_ready(response)
            except queue.Empty:
                time.sleep(0.001)
            except Exception as ex:
                logger.error(ex)
