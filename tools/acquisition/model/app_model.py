import json
import logging
import os
import time
import typing
from datetime import datetime
from pathlib import Path

import yaml

from autotrainer.core import ObservableObject, TriggerManager, CAPTURE_TRIGGER_ID, EventManager
from autotrainer.core import FixedArrayMultiQueue
from autotrainer.core import ProjectInfo
from autotrainer.core import AnimalSubject
from autotrainer.inference import PoseAlgorithm

from tools.acquisition.model.inference_model import InferenceModel
from tools.acquisition.model.behavior_model import BehaviorModel
from tools.acquisition.model.head_fix_model import HeadFixModel
from tools.acquisition.model.model_protocol import ModelProtocol
from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel
from tools.acquisition.model.user_preferences import UserPreferences
from tools.acquisition.model.video_capture_model import VideoCaptureModel

logger = logging.getLogger(__name__)


def _failed_camera_template(name: str, error: str):
    return f"Failed to start capture process for camera {name}:\n\t{error}\nPlease check all connections and settings."


class AppModel(ObservableObject):
    def __init__(self, preferences: UserPreferences, app_version: str = "", allow_can_emulation: bool = False):
        super().__init__(("on_error",))

        self._preferences = preferences

        self._app_version = app_version

        self._left_camera = VideoCaptureModel("left", self._preferences, 0)
        self._right_camera = VideoCaptureModel("right", self._preferences, 1)
        self._top_camera = VideoCaptureModel("web", self._preferences, -1)

        self._cameras = list([self._left_camera, self._right_camera, self._top_camera])

        self._head_fix = HeadFixModel(allow_can_emulation)

        self._pellet_delivery = PelletDeliveryModel(allow_can_emulation)

        self._inference_queue = None

        self._pose_algorithm = PoseAlgorithm()

        self._inference = InferenceModel(self._pose_algorithm)

        self._behavior = BehaviorModel(self.head_fix, self._pellet_delivery, self._inference)

        self._output_location = ""

        self._is_recording_trigger = False

        self._project_info = None

        self._animal_name = ""

        self._notes = ""

        self._models: typing.List[ModelProtocol] = [self._left_camera, self._right_camera, self._top_camera,
                                                    self._inference, self._behavior, self._head_fix,
                                                    self._pellet_delivery]

        self._animals: typing.List[AnimalSubject] = []

        self._selected_animal: typing.Optional[AnimalSubject] = None

        TriggerManager.instance().register(self._trigger_received, CAPTURE_TRIGGER_ID)

        self._head_fix.property_changed += self._on_head_fix_property_changed

        self._pellet_delivery.property_changed += self._on_pellet_property_changed

        self._load_animals()

    @property
    def preferences(self) -> UserPreferences:
        return self._preferences

    @property
    def project(self):
        return self._project_info

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
    def behavior(self):
        return self._behavior

    @property
    def inference(self):
        return self._inference

    @property
    def head_fix(self):
        return self._head_fix

    @property
    def pellet_delivery(self):
        return self._pellet_delivery

    @property
    def output_location(self) -> str:
        return self._output_location

    @property
    def animals(self) -> typing.List[AnimalSubject]:
        return self._animals

    @animals.setter
    def animals(self, value: typing.List[AnimalSubject]):
        self._animals = self._on_property_changed("animals", value, self._animals)

    @property
    def selected_animal(self) -> typing.Optional[AnimalSubject]:
        return self._selected_animal

    @selected_animal.setter
    def selected_animal(self, value: typing.Optional[AnimalSubject]):
        self._selected_animal = self._on_property_changed("selected_animal", value, self._selected_animal)

        if self._selected_animal is not None:
            self.property_changed("animal_name", self.animal_name, self.animal_name)
            self.head_fix.baseline_intensity = self._selected_animal.baseline_magnet_intensity
            self.head_fix.update_position(self._selected_animal.baseline_magnet_intensity)
            self.pellet_delivery.set_x(self._selected_animal.pellet_x)
            self.pellet_delivery.set_y(self._selected_animal.pellet_y)
            self.pellet_delivery.set_z(self._selected_animal.pellet_z)
        else:
            self.property_changed("animal_name", "(none)", "(none)")

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
        if self._selected_animal is not None:
            return self._selected_animal.name
        else:
            return "(none)"

    @animal_name.setter
    def animal_name(self, value: str):
        self._animal_name = self._on_property_changed("animal_name", value, self._animal_name)

    @property
    def notes(self) -> str:
        return self._notes

    @notes.setter
    def notes(self, value: str):
        self._notes = self._on_property_changed("notes", value, self._notes)

    def add_animal(self, name: str, select: bool = True):
        if not name or len(name) == 0:
            return

        animal = [x for x in self._animals if x.name == name]

        if len(animal) == 0:
            animal = AnimalSubject(name)
            animal.to_file(str(Path(self._preferences.animal_location).joinpath(f"{name}.json")))

            # Ensure property change events for listeners
            animals = self._animals.copy()
            animals.append(animal)

            self.animals = animals
        else:
            animal = animal[0]

        if select:
            self.selected_animal = animal

    def on_capture_start(self) -> bool:
        self._project_info = ProjectInfo(root=self.output_location, device_id=self._preferences.serial_number,
                                         ensure_exists=True, camera_1=self._left_camera.name,
                                         camera_2=self._right_camera.name, )

        for model in self._models:
            model.project = self._project_info

        self._behavior.on_prepare_capture()

        self._inference_queue = None

        if self._inference.is_enabled:
            shape_1 = self.left_camera.shape
            shape_2 = self.right_camera.shape
            if shape_1 == shape_2:
                self._inference_queue = FixedArrayMultiQueue(3, 2, 3, shape_1)
            else:
                logger.warning("pellet disabled: left and right camera frame sizes do not match")

        did_start = self.left_camera.on_prepare_capture(self._inference_queue)

        if not did_start:
            self.on_error("Camera Process Failed",
                          _failed_camera_template(self.left_camera.name, self.left_camera.last_error))

        if did_start:
            did_start = did_start and self.right_camera.on_prepare_capture(self._inference_queue)
            if not did_start:
                self.on_error("Camera Process Failed",
                              _failed_camera_template(self.right_camera.name, self.right_camera.last_error))

        if did_start:
            did_start = did_start and self.top_camera.on_prepare_capture()
            if not did_start:
                self.on_error("Camera Process Failed",
                              _failed_camera_template(self.top_camera.name, self.top_camera.last_error))

        if not did_start:
            logger.error("failed to start all subprocesses")
            self.on_capture_stop()
            return False

        self._save_project_metadata(self._project_info)

        if self._inference.is_enabled:
            self._inference.start(self._inference_queue)

        self.head_fix.connect_to_device()
        self._pellet_delivery.connect_to_device()

        for camera in self._cameras:
            if camera.is_primary:
                camera.on_capture_start()

        for camera in self._cameras:
            if not camera.is_primary:
                camera.on_capture_start()

        return True

    def on_capture_stop(self):
        self._inference.stop()

        self.head_fix.disconnect_from_device()
        self._pellet_delivery.disconnect_from_device()

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
                self._pellet_delivery.load_configuration(conf["pelletDelivery"])

            # TODO: renamed to "pellet".  Keep for backwards compatibility for a few iterations.
            if "analysis" in conf:
                self.inference.load_configuration(conf["analysis"])

            if "pellet" in conf:
                self.inference.load_configuration(conf["pellet"])

            if "behavior" in conf:
                self._behavior.load_configuration(conf["behavior"])

            if "outputLocation" in conf:
                self.output_location = conf["outputLocation"]
        except Exception as ex:
            logger.error(ex)
            return False

        return True

    def save_configuration(self, location: str):
        conf = self._configuration_as_dict()

        try:
            with open(location, "w") as file:
                yaml.dump(conf, file, sort_keys=False)
        except Exception as ex:
            logger.error(ex)
            return False

        return True

    def on_close(self):
        if self._inference is not None:
            self._inference.terminate()

        for camera in self._cameras:
            camera.on_close()

        EventManager.close()

        self.head_fix.on_close()
        self._pellet_delivery.on_close()

    def _load_animals(self):
        animals = []

        current_animal = self.selected_animal

        if self._preferences.animal_location is None or len(self._preferences.animal_location) == 0:
            default_location = Path.home().joinpath("Documents").joinpath("RawDataLocal").joinpath("Animals")

            try:
                default_location.mkdir(parents=True)
                self._preferences.animal_location = str(default_location)
            except Exception as e:
                logger.error(f"Failed to create default animal location {default_location}: {e}")
                return

        path = Path(self._preferences.animal_location)

        if path.exists() and path.is_dir():
            files = [x.name for x in path.iterdir() if not x.is_dir() and ".json" in x.name]
            loaded = [AnimalSubject.from_file(str(path.joinpath(x))) for x in files]
            animals = [x for x in loaded if x is not None]

        self.animals = animals

    def _trigger_received(self, _sender, _trigger_id, value):
        self._is_recording_trigger = value

        if value:
            self._save_metadata(self._project_info.get_metadata_file(-1), self._project_info.session.value)

    def _on_head_fix_property_changed(self, name: str, value, _):
        if name == "baseline_intensity" and self._selected_animal is not None:
            self._selected_animal.baseline_magnet_intensity = value
            self._save_animal_metadata()

    def _on_pellet_property_changed(self, name: str, value, _):
        if name == "x" and self._selected_animal is not None:
            self._selected_animal.pellet_x = value
            self._save_animal_metadata()
        elif name == "y" and self._selected_animal is not None:
            self._selected_animal.pellet_y = value
            self._save_animal_metadata()
        elif name == "z" and self._selected_animal is not None:
            self._selected_animal.pellet_z = value
            self._save_animal_metadata()

    def _save_animal_metadata(self):
        if self._selected_animal is not None:
            self._selected_animal.to_file(
                str(Path(self._preferences.animal_location).joinpath(f"{self._selected_animal.name}.json")))

    def _configuration_as_dict(self) -> dict:
        return {"camera1": self._left_camera.save_configuration(),
                "camera2": self._right_camera.save_configuration(),
                "camera3": self._top_camera.save_configuration(),
                "headFix": self.head_fix.save_configuration(),
                "pelletDelivery": self._pellet_delivery.save_configuration(),
                "pellet": self._inference.save_configuration(),
                "behavior": self._behavior.save_configuration(),
                "outputLocation": self.output_location}

    def _save_project_metadata(self, project_info: ProjectInfo):
        file_name = project_info.get_metadata_file()
        self._save_metadata(file_name, -1)

    def _save_metadata(self, file_name: str, session: int = None):
        now = datetime.now()

        info = {
            "date": now.strftime("%Y%m%d_%H%M%S"),
            "created": now.timestamp(),
            "createdUtc": datetime.utcnow().timestamp(),
            "serialNumber": self._preferences.serial_number or "",
            "appVersion": self._app_version,
            "animalName": self.animal_name,
            "notes": self.notes or "",
            "session": session,
            "configuration": self._configuration_as_dict()
        }

        try:
            with open(file_name + ".json", "w") as file:
                json.dump(info, file)
            with open(file_name + ".yaml", "w") as file:
                yaml.dump(info, file, sort_keys=False)
        except Exception as ex:
            logger.error(ex)
