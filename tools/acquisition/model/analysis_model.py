import logging
import queue
import time
from multiprocessing import Queue
from threading import Thread

from PySide6.QtCore import QObject, Signal
from events import Events

from autotrainer.core import FixedArrayMultiQueue
from autotrainer.inference import PosePredict, AnalysisMessageKind
from autotrainer.inference.dlc.dlc_pose_model import DlcPoseModel
from inference_algorithms import PelletOnlyPoseAlgorithm

from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel
from tools.acquisition.inference.pellet_device_response_api import PelletDeviceResponseApi

logger = logging.getLogger(__name__)


class AnalysisModel(QObject):
    pose_ready = Signal(object)

    def __init__(self, pellet: PelletDeliveryModel):
        super().__init__()

        # TODO remove Qt dependency, inherit from Events
        self.events = Events(("property_changed",))

        self._data_queue = Queue()
        self._cmd_queue = Queue()
        self._msg_queue = Queue()

        self._is_enabled = False
        self._model_location = ""
        self._response_api = PelletDeviceResponseApi(self, pellet)
        self._algorithm = PelletOnlyPoseAlgorithm()
        self._algorithm.api = self._response_api
        self._pellet_model = pellet
        self._pellet_model.pellet_reader.ack_received += lambda ack: self._algorithm.api_response(ack, True)

        self._msg_thread = None
        self._data_thread = None

        self._process = None

        self._is_running = True

        self._is_pose_predict_enabled = True

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value: bool):
        if self._is_enabled == value:
            return

        old_value = self._is_enabled

        self._is_enabled = value

        self.events.property_changed("is_enabled", value, old_value)

    @property
    def is_pose_predict_enabled(self) -> bool:
        return self._is_pose_predict_enabled

    @is_pose_predict_enabled.setter
    def is_pose_predict_enabled(self, value: bool):
        if self._is_pose_predict_enabled == value:
            return

        old_value = self._is_pose_predict_enabled

        self._is_pose_predict_enabled = value

        self.events.property_changed("is_pose_predict_enabled", value, old_value)

    @property
    def model_location(self) -> str:
        return self._model_location

    @model_location.setter
    def model_location(self, value: str):
        if self._model_location == value:
            return

        old_value = self._model_location

        self._model_location = value

        self.events.property_changed("model_location", value, old_value)

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

        if self._model_location is None or len(self._model_location) == 0:
            logger.warning("analysis not started because the model not specified")
            return False

        model = DlcPoseModel(self._model_location, 1, 0, network_queue.batch_size)

        if not model.is_valid():
            logger.warning("analysis not started because the model does not exist at the specified location")
            return False

        self._process = PosePredict(model, network_queue, self._data_queue, self._cmd_queue, self._msg_queue)

        self._process.start()

    def stop(self):
        if self._process is not None:
            self._cmd_queue.put(AnalysisMessageKind.Terminate)

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

    def _monitor_msg_queue(self):
        while self._is_running:
            try:
                msg, context = self._msg_queue.get(block=False, timeout=0.5)
                if msg == AnalysisMessageKind.Initialized:
                    logger.info(msg)
                    self._algorithm.set_parts(context)
                    self._algorithm.initialize()
                    self._cmd_queue.put(AnalysisMessageKind.Start)
                elif msg == AnalysisMessageKind.Performance:
                    logger.info(f"{context[0] :.1f} predict/s")
                    logger.info(f"{context[1] :.1f} frames/camera/s ({(context[1] * 2):.1f} total images/s)")
            except queue.Empty:
                time.sleep(0.001)
            except Exception as ex:
                logger.error(ex)

    def _monitor_data_queue(self):
        while self._is_running:
            try:
                pose_data = self._data_queue.get(block=False, timeout=0.5)
                if self._is_pose_predict_enabled:
                    vis_data = self._algorithm.process(pose_data)
                    self.pose_ready.emit(vis_data)
            except queue.Empty:
                time.sleep(0.001)
            except Exception as ex:
                logger.error(ex)
