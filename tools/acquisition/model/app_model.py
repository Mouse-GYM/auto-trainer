import json
import logging
import multiprocessing
import queue
import time
import typing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from autotrainer.core import (ObservableObject, EventManager, SystemMessageHandler, MessageHandler, SystemConfiguration,
                              CameraId, PersistenceConfiguration, HardwareConfiguration, Notification,
                              get_system_configuration_dumper, NotificationCenter, TriggerNotification)
from autotrainer.core import FixedArrayMultiQueue
from autotrainer.core import ProjectInfo
from autotrainer.core import AnimalSubject
from autotrainer.core.multiproc import get_mp_ctx
from autotrainer.inference import PoseAlgorithm
from tools.acquisition.model.hardware_model import HardwareModel

from tools.acquisition.model.inference_model import InferenceModel
from tools.acquisition.model.behavior_model import BehaviorModel
from tools.acquisition.model.project_dependent_protocol import ProjectDependentProtol
from tools.acquisition.model.user_preferences import UserPreferences
from tools.acquisition.model.video_capture_model import VideoCaptureModel

logger = logging.getLogger(__name__)


def _failed_camera_template(name: str, error: str):
    return f"Failed to start capture process for camera {name}:\n\t{error}\nPlease check all connections and settings."


class AppModel(ObservableObject):
    def __init__(self, preferences: UserPreferences, app_version: str = ""):
        super().__init__(("on_error",))

        self._preferences = preferences

        self._app_version = app_version

        self._left_camera = VideoCaptureModel("left", self._preferences, 0)
        self._right_camera = VideoCaptureModel("right", self._preferences, 1)
        self._top_camera = VideoCaptureModel("web", self._preferences, -1)

        self._cameras = [self._left_camera, self._right_camera, self._top_camera]

        self._message_queue = queue.Queue()
        self._message_handler = SystemMessageHandler(self._message_queue)

        # Use the default analysis object created by the message handler.  Dereferenced here for use in the class in
        # case that changes.
        self._analysis = self._message_handler.analysis

        self._hardware = HardwareModel(self._message_handler)

        self._inference_queue = None

        self._pose_algorithm = PoseAlgorithm()

        self._inference = InferenceModel(self._pose_algorithm)

        self._behavior = BehaviorModel(self._message_handler, self._analysis, self._hardware, self._inference)

        self._output_location = ""

        self._is_recording_trigger = False

        self._project_info = None

        self._animal_name = ""

        self._notes = ""

        self._models: typing.List[ProjectDependentProtol] = [self._left_camera, self._right_camera, self._top_camera,
                                                             self._inference, self._behavior]

        self._animals: typing.List[AnimalSubject] = []

        self._selected_animal: typing.Optional[AnimalSubject] = None

        NotificationCenter.default_center().add_observer(TriggerNotification.CAPTURE_ID, self._trigger_received)

        self._message_handler.property_changed += self._on_message_handler_property_changed
        self._behavior.algorithm.property_changed += self._on_behavior_algo_property_changed
        self._behavior.property_changed += self._on_behavior_property_changed

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
    def analysis(self):
        return self._analysis

    @property
    def inference(self):
        return self._inference

    @property
    def hardware(self):
        return self._hardware

    @property
    def message_handler(self) -> MessageHandler:
        return self._message_handler

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
            self.behavior.algorithm.baseline_intensity = self._selected_animal.baseline_magnet_intensity
            self.hardware.update_head_magnet_intensity(self._selected_animal.baseline_magnet_intensity)
            self.hardware.set_x(self._selected_animal.pellet_x)
            self.hardware.set_y(self._selected_animal.pellet_y)
            self.hardware.set_z(self._selected_animal.pellet_z)
        else:
            self.property_changed("animal_name", "(none)", "(none)")

    @output_location.setter
    def output_location(self, value: str):
        if self._output_location == value:
            return

        old_value = self._output_location

        self._output_location = value

        self.property_changed("output_location", value, old_value)

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
                self._inference_queue = FixedArrayMultiQueue(
                    16,
                    2,
                    3,
                    shape_1,
                    name="inference_q",
                    mp_ctx=get_mp_ctx(),
                )
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

        if self._analysis is not None:
            self._analysis.project_info = self._project_info

        for camera in self._cameras:
            if camera.is_primary:
                camera.on_capture_start()

        for camera in self._cameras:
            if not camera.is_primary:
                camera.on_capture_start()

        logger.debug("connecting hardware ...")
        self.hardware.connect(self._message_handler.input_queue, self._selected_animal)
        logger.info("finished connecting hardware")

        return True

    def on_capture_stop(self):
        self._inference.stop()

        self.hardware.disconnect()

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

        if self._analysis is not None:
            self._analysis.project_info = None

        self._is_recording_trigger = False

    def load_configuration(self, location: str):
        if not location or not Path(location).is_file():
            logger.info(f"did not receive explicit configuration file, trying default")
            # Check to see if there is a file in the new default location.  If so, use it.
            location = Path(self._preferences.configuration_location)
            location.mkdir(parents=True, exist_ok=True)
            configuration = SystemConfiguration.load_default(str(location))

            # Fallback to the old last configuration preference if this device has not converted.
            # TODO - remove this once all devices have migrated.
            if configuration is None:
                logger.info(f"default not yet in use, trying last configuration")
                location = self._preferences.last_configuration
                configuration = SystemConfiguration.load_yaml_file(location)

                if configuration is not None:
                    # Migrate to new default location.
                    configuration.save_default(self._preferences.configuration_location)
        else:
            # Always allow for a custom configuration file if provided.
            logger.info(f"using explicit configuration")
            configuration: SystemConfiguration = SystemConfiguration.load_yaml_file(location)

        if configuration is None:
            configuration = SystemConfiguration()
            logger.info(f"using default configuration")
        else:
            logger.info(f"using configuration from {location}")

        if (camera := configuration.get_camera(CameraId.Left)) is not None:
            self._left_camera.load_configuration(camera)
        if (camera := configuration.get_camera(CameraId.Right)) is not None:
            self._right_camera.load_configuration(camera)
        if (camera := configuration.get_camera(CameraId.Web)) is not None:
            self._top_camera.load_configuration(camera)

        self._hardware.tunnel_identifier = configuration.hardware.tunnel_identifier
        self._hardware.pellet_identifier = configuration.hardware.pellet_identifier

        self.inference.load_configuration(configuration.inference)
        self.behavior.load_configuration(configuration.behavior)

        self._analysis.headbar_pressure_monitor.load_configuration(configuration.behavior.headbar_pressure)
        self._analysis.load_cell_monitor.load_configuration(configuration.behavior.load_cell)
        self._analysis.load_cell_tare_monitor.load_configuration(configuration.behavior.auto_tare)

        self.output_location = configuration.persistence.output_location

        return True

    def save_configuration(self):
        conf = self._create_configuration()

        return conf.save_default(self._preferences.configuration_location)

    def on_activated(self):
        self._message_handler.start()

    def on_close(self):
        if self._inference is not None:
            self._inference.terminate()

        for camera in self._cameras:
            camera.on_close()

        EventManager.default().close()

        self.hardware.disconnect()
        self._message_handler.request_terminate()

        self.save_configuration()

    def _load_animals(self):
        animals = []

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

    def _trigger_received(self, notification: Notification):
        self._is_recording_trigger = notification.context

        if notification.context and self._project_info is not None:
            self._save_metadata(self._project_info.get_metadata_file(-1), self._project_info.session.value)

    def _on_behavior_property_changed(self, name: str, new_value, old_value):
        logger.debug("behavior property changed: %s: %s -> %s", name, old_value, new_value)

    def _on_behavior_algo_property_changed(self, name: str, value, _):
        if name == "baseline_intensity" and self._selected_animal is not None:
            self._selected_animal.baseline_magnet_intensity = value
            self._save_animal_metadata()

    def _on_message_handler_property_changed(self, name: str, value, _):
        if name == MessageHandler.DEVICE_X_PROPERTY and self._selected_animal is not None:
            self._selected_animal.pellet_x = value
            self._save_animal_metadata()
        elif name == MessageHandler.DEVICE_Y_PROPERTY and self._selected_animal is not None:
            self._selected_animal.pellet_y = value
            self._save_animal_metadata()
        elif name == MessageHandler.DEVICE_Z_PROPERTY and self._selected_animal is not None:
            self._selected_animal.pellet_z = value
            self._save_animal_metadata()

    def _save_animal_metadata(self):
        if self._selected_animal is not None:
            self._selected_animal.to_file(
                str(Path(self._preferences.animal_location).joinpath(f"{self._selected_animal.name}.json")))

    def _create_configuration(self) -> SystemConfiguration:
        hardware_configuration = HardwareConfiguration(tunnel_identifier=self._hardware.tunnel_identifier,
                                                       pellet_identifier=self._hardware.pellet_identifier)

        cameras = []
        for camera in self._cameras:
            cameras.append(camera.save_configuration())

        configuration = SystemConfiguration(cameras=cameras,
                                            hardware=hardware_configuration,
                                            inference=self._inference.save_configuration(),
                                            behavior=self._behavior.save_configuration(),
                                            persistence=PersistenceConfiguration(output_location=self.output_location))

        return configuration

    def _save_project_metadata(self, project_info: ProjectInfo):
        file_name = project_info.get_metadata_file()
        self._save_metadata(file_name, -1)

    def _save_metadata(self, file_name: str, session: int = None):
        now = datetime.now()

        info = {
            "date": now.strftime("%Y%m%d_%H%M%S"),
            "created": now.timestamp(),
            "createdUtc": datetime.now(timezone.utc).timestamp(),
            "serialNumber": self._preferences.serial_number or "",
            "appVersion": self._app_version,
            "animalName": self.animal_name,
            "notes": self.notes or "",
            "session": session,
            "configuration": None
        }

        configuration = self._create_configuration()

        try:
            with open(file_name + ".json", "w") as file:
                out = info.copy()
                out["configuration"] = asdict(configuration)
                json.dump(out, file)
            with open(file_name + ".yaml", "w") as file:
                out = info.copy()
                out["configuration"] = configuration
                yaml.dump(out, file, Dumper=get_system_configuration_dumper(), sort_keys=False)
        except Exception as ex:
            logger.error(ex)
