import ctypes
import json
import logging
import os
import time
from multiprocessing import Value
from datetime import datetime

import yaml

from autotrainer.core import ObservableObject, TriggerManager, CAPTURE_TRIGGER_ID
from autotrainer.core import FixedArrayMultiQueue
from autotrainer.core.project import ProjectInfo
from tools.acquisition.behavior.behavior_model_transitions import BehaviorModelTransitions

from tools.acquisition.model.analysis_model import AnalysisModel
from tools.acquisition.model.head_fix_model import HeadFixModel
from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel
from tools.acquisition.model.user_preferences import UserPreferences
from tools.acquisition.model.video_capture_model import VideoCaptureModel

logger = logging.getLogger(__name__)


def _failed_camera_template(name: str, error: str):
    return f"Failed to start capture process for camera {name}:\n\t{error}\nPlease check all connections and settings."


class AppModel(ObservableObject):
    def __init__(self, preferences: UserPreferences):
        super().__init__(("on_error",))

        self._preferences = preferences

        self._left_camera = VideoCaptureModel("left", self._preferences, 0)
        self._right_camera = VideoCaptureModel("right", self._preferences, 1)
        self._top_camera = VideoCaptureModel("web", self._preferences, -1)

        self._cameras = list([self._left_camera, self._right_camera, self._top_camera])

        self._head_fix = HeadFixModel()

        self.pellet_delivery = PelletDeliveryModel()

        self._inference_queue = None

        self._analysis = AnalysisModel(self.pellet_delivery)

        self._behavioral = BehaviorModelTransitions(self._head_fix, self.pellet_delivery)

        self._output_location = ""

        self._is_recording_trigger = False

        self._project_info = None

        self._next_session = Value(ctypes.c_uint32, 0)

        self._animal_name = ""

        self._notes = ""

        TriggerManager.instance().register(self._trigger_received, CAPTURE_TRIGGER_ID)

    @property
    def preferences(self) -> UserPreferences:
        return self._preferences

    @property
    def left_camera(self):
        return self._left_camera

    @property
    def right_camera(self):
        return self._right_camera

    @property
    def top_camera(self):
        return self._top_camera

    @property
    def analysis(self):
        return self._analysis

    @property
    def head_fix(self):
        return self._head_fix

    @property
    def output_location(self) -> str:
        return self._output_location

    @output_location.setter
    def output_location(self, value: str):
        if self._output_location == value:
            return

        old_value = self._output_location

        self._output_location = value

        self.property_changed("output_location", value, old_value)

        self._head_fix.output_location = value

    @property
    def animal_name(self) -> str:
        return self._animal_name

    @animal_name.setter
    def animal_name(self, value: str):
        self._animal_name = self._on_property_changed("animal_name", value, self._animal_name)

    @property
    def notes(self) -> str:
        return self._notes

    @notes.setter
    def notes(self, value: str):
        self._notes = self._on_property_changed("notes", value, self._notes)

    def on_capture_start(self) -> bool:
        self.create_project_info()

        self._inference_queue = None

        if self._analysis.is_enabled:
            shape_1 = self.left_camera.shape
            shape_2 = self.right_camera.shape
            if shape_1 == shape_2:
                self._inference_queue = FixedArrayMultiQueue(3, 2, 3, shape_1)

        did_start = self.left_camera.on_prepare_capture(self._project_info, self._next_session, self._inference_queue)

        if not did_start:
            self.on_error("Camera Process Failed",
                          _failed_camera_template(self.left_camera.name, self.left_camera.last_error))

        if did_start:
            did_start = did_start and self.right_camera.on_prepare_capture(self._project_info, self._next_session,
                                                                           self._inference_queue)
            if not did_start:
                self.on_error("Camera Process Failed",
                              _failed_camera_template(self.right_camera.name, self.right_camera.last_error))

        if did_start:
            did_start = did_start and self.top_camera.on_prepare_capture(self._project_info, self._next_session)
            if not did_start:
                self.on_error("Camera Process Failed",
                              _failed_camera_template(self.top_camera.name, self.top_camera.last_error))

        if not did_start:
            logger.error("failed to start all subprocesses")
            self.on_capture_stop()
            return False

        self._save_project_metadata(self._project_info)

        if self._analysis.is_enabled:
            self._analysis.start(self._inference_queue)

        self.head_fix.connect_to_device(self._project_info)
        self.pellet_delivery.connect_to_device()

        for camera in self._cameras:
            if camera.is_primary:
                camera.on_capture_start()

        for camera in self._cameras:
            if not camera.is_primary:
                camera.on_capture_start()

        return True

    def on_capture_stop(self):
        self._analysis.stop()

        self.head_fix.disconnect_from_device()
        self.pellet_delivery.disconnect_from_device()

        for camera in self._cameras:
            if not camera.is_primary:
                camera.on_capture_notify_end()

        time.sleep(0.01)

        for camera in self._cameras:
            if camera.is_primary:
                camera.on_capture_notify_end()

        for camera in self._cameras:
            if not camera.is_primary:
                camera.on_capture_stop()

        for camera in self._cameras:
            if camera.is_primary:
                camera.on_capture_stop()

        self._is_recording_trigger = False

    def load_configuration(self, location: str):
        if not location or not os.path.isfile(location):
            return False

        logger.info(f"loading configuration from {location}")

        try:
            with open(location, "r") as file:
                conf = yaml.safe_load(file)

            if "camera1" in conf:
                self._left_camera.load_configuration(conf["camera1"])
            if "camera2" in conf:
                self._right_camera.load_configuration(conf["camera2"])
            if "camera3" in conf:
                self._top_camera.load_configuration(conf["camera3"])

            if "headFix" in conf:
                self.head_fix.load_configuration(conf["headFix"])
            if "pelletDelivery" in conf:
                self.pellet_delivery.load_configuration(conf["pelletDelivery"])

            if "analysis" in conf:
                self.analysis.load_configuration(conf["analysis"])

            if "outputLocation" in conf:
                self.output_location = conf["outputLocation"]
        except Exception as ex:
            logger.error(ex)
            return False

        return True

    def save_configuration(self, location: str):
        conf = {"camera1": self._left_camera.write_configuration(),
                "camera2": self._right_camera.write_configuration(),
                "camera3": self._top_camera.write_configuration(),
                "headFix": self.head_fix.write_configuration(),
                "pelletDelivery": self.pellet_delivery.write_configuration(),
                "analysis": self._analysis.write_configuration(),
                "outputLocation": self.output_location}

        try:
            with open(location, "w") as file:
                yaml.dump(conf, file, sort_keys=False)
        except Exception as ex:
            logger.error(ex)
            return False

        return True

    def on_close(self):
        if self._analysis is not None:
            self._analysis.terminate()

        for camera in self._cameras:
            camera.on_close()

        self.head_fix.on_close()
        self.pellet_delivery.on_close()

    def _trigger_received(self, _sender, _trigger_id, context):
        self._is_recording_trigger = context

        # Wait until the end of the trigger to increment.
        if not context:
            self._next_session.value += 1
        else:
            self._save_metadata(self._project_info.get_metadata_file(self._next_session.value),
                                self._next_session.value)

    def _save_project_metadata(self, project_info: ProjectInfo):
        file_name = project_info.get_metadata_file()
        self._save_metadata(file_name, -1)

    def _save_metadata(self, file_name: str, session: int = None):
        now = datetime.now()

        info = {
            "date": now.strftime("%Y%m%d_%H%M%S"),
            "created": now.timestamp(),
            "created_utc": datetime.utcnow().timestamp(),
            "serialNumber": self._preferences.serial_number or "",
            "animalName": self.animal_name or "",
            "notes": self.notes or "",
            "session": session
        }

        with open(file_name, "w") as file:
            json.dump(info, file)

    def create_project_info(self) -> None:
        self._project_info = ProjectInfo(root=self.output_location, device_id=self._preferences.serial_number,
                                         ensure_exists=True)

        self._next_session.value = self._project_info.calculate_next_session_index()

        location, _ = self._project_info.get_day_path()
