import logging
import os
import queue
from multiprocessing import Queue
from threading import Thread

from PySide6.QtCore import QObject, Signal
from autotrainer.circular_image_buffer import CircularImageBuffer
from autotrainer.dlc.pose_predict import PosePredict, AnalysisMessageKind

from tools.acquisition.default_dlc_algorithm import DefaultDLCAlgorithm
from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel
from tools.acquisition.model.user_settings import UserSettings
from tools.acquisition.pellet_device_response_api import PelletDeviceResponseApi

logger = logging.getLogger(__name__)


class AnalysisModel(QObject):
    pose_ready = Signal(object)

    def __init__(self, settings: UserSettings, pellet: PelletDeliveryModel):
        super().__init__()

        self._settings = settings

        self._data_queue = Queue()
        self._cmd_queue = Queue()
        self._msg_queue = Queue()

        self._is_enabled = self._settings.analysis_enabled
        self._model_location = self._settings.analysis_model
        self._algorithm_location = self._settings.analysis_algorithm
        self._response_api = PelletDeviceResponseApi(pellet)
        self._algorithm = DefaultDLCAlgorithm()
        self._algorithm.api = self._response_api
        pellet.pellet_reader.command_ack.connect(lambda x: self._algorithm.api_response(x, True))

        self._msg_thread = None
        self._data_thread = None

        self._process = None

        self._is_running = True

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value: bool):
        self._is_enabled = value
        self._settings.analysis_enabled = value

    @property
    def model_location(self) -> str:
        return self._model_location

    @model_location.setter
    def model_location(self, value: str):
        self._model_location = value
        self._settings.analysis_model = value

    @property
    def algorithm_location(self) -> str:
        return self._algorithm_location

    @algorithm_location.setter
    def algorithm_location(self, value: str):
        self._algorithm_location = value
        self._settings.analysis_algorithm = value

    def start(self, network_queue: CircularImageBuffer) -> bool:
        if self._msg_thread is None:
            self._msg_thread = Thread(target=self._monitor_msg_queue)
            self._msg_thread .start()

        if self._data_thread is None:
            self._data_thread = Thread(target=self._monitor_data_queue)
            self._data_thread.start()

        if network_queue is None:
            logger.warning("analysis not started because there is no network image queue")
            return False

        if self._model_location is None or len(self._model_location) == 0:
            logger.warning("analysis not started because the model not specified")
            return False

        model_location = os.path.join(self._model_location, "config.yaml")
        if not os.path.isfile(model_location):
            logger.warning("analysis not started because the model does not exist at the specified location")
            return False

        self._process = PosePredict(self._model_location, network_queue, self._data_queue, self._cmd_queue, self._msg_queue)
        self._process.start()

    def stop(self):
        if self._process is not None:
            self._cmd_queue.put(AnalysisMessageKind.Terminate)
            self._process = None

    def terminate(self):
        self.stop()

        self._is_running = False

    def _monitor_msg_queue(self):
        while self._is_running:
            try:
                msg, context = self._msg_queue.get(block=False, timeout=0.5)
                if msg == AnalysisMessageKind.Initialized:
                    logger.info(msg)
                    self._algorithm.set_parts(context)
                    self._algorithm.initialize()
                    self._cmd_queue.put(AnalysisMessageKind.Start)
            except queue.Empty:
                pass
            except Exception as ex:
                logger.error(ex)

    def _monitor_data_queue(self):
        while self._is_running:
            try:
                pose_data = self._data_queue.get(block=False, timeout=0.5)
                vis_data = self._algorithm.process(pose_data)
                self.pose_ready.emit(vis_data)
            except queue.Empty:
                pass
            except Exception as ex:
                logger.error(ex)
