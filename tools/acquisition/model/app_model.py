import enum
import functools
import json
import logging
import pickle
import queue
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

import yaml

from autotrainer.behavior import IntersessionState, BehaviorAlgorithm
from autotrainer.core.analysis import calibration_FLIR
from autotrainer.core import (ObservableObject, EventManager, SystemMessageHandler, SystemConfiguration,
                              CameraId, PersistenceConfiguration, HardwareConfiguration, Notification,
                              NotificationCenter, TriggerNotification, SystemStatusMessageKind, SensorAnalysis)
from autotrainer.core import FixedArrayMultiQueue
from autotrainer.core import ProjectInfo
from autotrainer.core import AnimalSubject
from autotrainer.core.configuration import SystemConfigurationDumper
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import get_mp_ctx, make_daemon_timer
from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.core.analysis.config import load_calib_stereo_params
from autotrainer.inference import PoseAlgorithm, InferenceStatus
from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.video import CaptureProcessStatus

from tools.acquisition.model.hardware_model import HardwareModel
from tools.acquisition.model.inference_model import InferenceModel
from tools.acquisition.model.behavior_model import BehaviorModel
from tools.acquisition.model.project_dependent_protocol import ProjectDependentProtol
from tools.acquisition.model.user_preferences import UserPreferences
from tools.acquisition.model.video_capture_model import VideoCaptureModel
from tools.acquisition.view.analysis_content import AVAILABLE_GRAPHS

logger = get_verbose_logger(__name__)


# allow be patched from tests
_recording_age_enough_timer = make_daemon_timer


def _failed_camera_template(name: str, error: str):
    return f"Failed to start capture process for camera {name}:\n\t{error}\nPlease check all connections and settings."


class AppModel(ObservableObject):

    class Props(str, enum.Enum):
        SELECTED_ANIMAL = "selected_animal"

    def __init__(
        self,
        preferences: UserPreferences,
        app_version: str = "",
        *,
        calib_dir: Optional[Path] = None,
    ):
        super().__init__(("on_error",))

        self._preferences = preferences
        self._loaded_configuration: Optional[SystemConfiguration] = None

        self._app_version = app_version

        mp_ctx = get_mp_ctx()

        # not sure this should better be in SystemMachine or BehaviorAlgo or BehaviorModel or eventually HardwareModel ?
        # although here it's also working, so keeping for now.
        proc_msg_queue = self._multiproc_msg_queue = mp_ctx.Queue()
        self._handle_proc_msg_thread = threading.Thread(
            target=self._handle_proc_msg_queue, name="handle_proc_msg_queue", daemon=True)
        self._handle_proc_msg_thread.start()
        self._timer_recording_age_enough = _recording_age_enough_timer(0, lambda: None)
        # end not sure

        self._left_camera = VideoCaptureModel("left", self._preferences, 0,
                                              msg_queue=proc_msg_queue)
        self._right_camera = VideoCaptureModel("right", self._preferences, 1,
                                               msg_queue=proc_msg_queue)

        self._top_camera_presence_detection = PresenceDetectionAttrs()
        self._top_camera = VideoCaptureModel("web", self._preferences, -1,
                                             presence_detection=self._top_camera_presence_detection,
                                             msg_queue=None)  # not interested to webcam status for now.

        self._cameras = [  # must respect camera_idx/inference_index order
            self._left_camera,
            self._right_camera,
            self._top_camera,
        ]

        self._system_message_queue = queue.Queue()  # only dedicated to CAN bus messages reading/handling
        # so: using a multiprocess queue instead, would allow to put the CAN connection thread into a dedicated process,
        # also giving more space/freedom for the main/UI process python GIL acquire/release.
        sensor_analysis = self._analysis = SensorAnalysis(topcam_presence=self._top_camera_presence_detection)
        #
        self._system_message_handler = SystemMessageHandler(self._system_message_queue,
                                                            sensor_analysis=sensor_analysis)
        self._system_message_handler.start()

        self._hardware = HardwareModel(self._system_message_handler)

        self._inference_queue = None

        calib_src_dir = (
            Path("~/Autotrainer/4mm_6r_8c_4x") if calib_dir is None
            else calib_dir
        ).expanduser()
        if calib_src_dir.exists():
            self._stereo_params = load_calib_stereo_params(
                calib_src_dir.joinpath('camera_matrix', 'stereo_params.pickle')
            )
            metadata_path = calib_src_dir.joinpath('calibration_userset.yaml')
            with metadata_path.open() as fh:
                self._calib_metadata = yaml.safe_load(fh)

            square_size, _, _ = calibration_FLIR.get_calibration_info(calib_src_dir.as_posix())
            cam_names = calibration_FLIR.get_video_list(calib_src_dir.as_posix())
            path_offsets = calib_src_dir.joinpath('camera_offsets.pkl')
            with open(path_offsets, "rb") as fh:
                cam_offsets = pickle.load(fh)
        else:
            self._stereo_params = None
            self._calib_metadata = None
            square_size = None
            cam_names = None
            cam_offsets = None
            logger.warning("calib_src_dir=%r does not exist", calib_src_dir.as_posix())

        self._pose_algorithm = PoseAlgorithm(
            stereo_params=self._stereo_params,
            calib_metadata=self._calib_metadata,
            cam_names=cam_names,
            square_size=square_size,
            cam_offsets=cam_offsets,
        )

        self._inference = InferenceModel(self._pose_algorithm, calib_dir=calib_dir)

        behavior = self._behavior = BehaviorModel(
            self._system_message_handler, self._analysis, self._hardware, self._inference)
        behavior.algorithm.top_camera_presence_detection = self._top_camera_presence_detection

        self._output_location = ""

        self._is_recording_trigger = False

        self._project_info = None

        self._animal_name = ""

        self._notes = ""

        self._models: List[ProjectDependentProtol] = [
            self._left_camera,
            self._right_camera,
            self._top_camera,
            self._inference,
            self._behavior,
        ]

        self._animals: List[AnimalSubject] = []

        self._selected_animal: Optional[AnimalSubject] = None

        NotificationCenter.default_center().add_observer(TriggerNotification.CAPTURE_ID, self._trigger_received)

        self._hardware.property_changed += self._on_hardware_property_changed
        self._behavior.algorithm.property_changed += self._on_behavior_algo_property_changed
        self._behavior.property_changed += self._on_behavior_model_property_changed
        preferences.property_changed += self._on_preferences_property_changed
        self._inference.property_changed += self._on_inference_property_changed

        self._load_animals()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _consider_release_pellet(self):
        algo = self._behavior.algorithm
        # we never know the session could be just stopped,
        # so check:
        if algo.is_in_session:
            logger.verbose("consider_release_pellet: calling try_next_state ; "
                           "pellet_recently_seen=%s age=%.2f",
                           algo.pellet_recently_seen, algo.pellet_seen_age)
            #   and algo.capture_status_age >= algo.recording_age_release_pellet_threshold:
            # this is called via a timer, which are not necessarily very precise,
            # and to be safe on all side, do not check again, the actual age could even be slightly less than the
            # desired threshold (but very very near). So to not miss that case: do not "recheck"
            self._behavior.system_machine.pellet.environment_changed(
                pellet_seen=algo.pellet_recently_seen, must_release=True, caller="camera-start-recording")
        else:
            logger.verbose("consider_release_pellet but not in session")

    def _handle_proc_msg_queue(self):
        proc_msg_q = self._multiproc_msg_queue
        logger.info("handle_proc_msg_queue now running")
        while True:
            raw = proc_msg_q.get()
            if raw is None:
                break
            args = ()
            kwargs = None
            if isinstance(raw, tuple):
                if len(raw) < 1:
                    logger.warning("Invalid status msg: %r", raw)
                    continue
                cmd = raw[0]
                if len(raw) > 1:
                    args = raw[1]
                    if len(raw) > 2:
                        kwargs = raw[2]
                        if len(raw) > 3:
                            logger.warning("Unhandled extra args to status msg: %r", raw[3:])
            else:
                cmd = raw
            extra_info = (args, kwargs) if logger.isEnabledFor(logging.DEBUG) else "NA"
            logger.info("Handling %s ; data=%s", cmd, extra_info)
            algo = self._behavior.algorithm
            if cmd == SystemStatusMessageKind.CAMERA_STATUS_CHANGE:
                cam_idx, new_status = args
                if self._cameras[cam_idx].is_primary:
                    algo.capture_status = new_status  # first
                    self._timer_recording_age_enough.cancel()
                    if new_status == CaptureProcessStatus.RECORDING:
                        new_timer = self._timer_recording_age_enough = _recording_age_enough_timer(
                            algo.recording_age_release_pellet_threshold, self._consider_release_pellet
                        )
                        new_timer.start()
                        logger.debug("started timer for consider_release_pellet, delay=%s",
                                     algo.recording_age_release_pellet_threshold)
                else:
                    logger.verbose("not handling non-primary camera status, cam_idx=%s status=%s",
                                   cam_idx, new_status)
        # end while True
        logger.info("handle_proc_msg_queue exiting")

    @property
    def preferences(self) -> UserPreferences:
        return self._preferences

    @property
    def loaded_configuration(self):
        return self._loaded_configuration

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
    def top_camera_presence_detection(self):
        return self._behavior.algorithm.top_camera_presence_detection

    @property
    def behavior(self):
        return self._behavior

    @property
    def analysis(self):
        return self._analysis

    @property
    def inference(self) -> InferenceModel:
        return self._inference

    @property
    def hardware(self):
        return self._hardware

    @property
    def message_handler(self) -> SystemMessageHandler:
        return self._system_message_handler

    @property
    def output_location(self) -> str:
        return self._output_location

    @property
    def animals(self) -> List[AnimalSubject]:
        return self._animals

    @animals.setter
    def animals(self, value: List[AnimalSubject]):
        self._animals = self._on_property_changed("animals", value, self._animals)

    @property
    def selected_animal(self) -> Optional[AnimalSubject]:
        return self._selected_animal

    @selected_animal.setter
    def selected_animal(self, selected_animal: Optional[AnimalSubject]):
        algo = self._behavior.algorithm
        prev, self._selected_animal = self._selected_animal, selected_animal
        self._on_property_changed(self.Props.SELECTED_ANIMAL, selected_animal, prev)
        self._preferences.selected_animal = "" if selected_animal is None else selected_animal.name
        if selected_animal is not None and prev != selected_animal:
            hardware = self.hardware
            self.property_changed("animal_name", selected_animal.name, self.animal_name)
            algo.baseline_intensity = selected_animal.baseline_magnet_intensity
            algo.reset_selected_animal(selected_animal)
            hardware.update_head_magnet_intensity(selected_animal.baseline_magnet_intensity)
            hardware.set_x(self._selected_animal.pellet_x)
            hardware.set_y(self._selected_animal.pellet_y)
            hardware.set_z(self._selected_animal.pellet_z)
            hardware.send_pellet()
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
        # not used actually
        self._preferences.selected_animal = value
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
            animal.to_file(Path(self._preferences.animal_location).joinpath(f"{name}.json"))

            # Ensure property change events for listeners
            animals = self._animals.copy()  # not sure why we don't append directly instead of copy+append+setattr
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
                    # live queue does not need/require a lot of "depth" == total nbr of batches that can sit
                    # in the ring-buffer-queue at the same time.
                    3,
                    2,
                    3,
                    shape=shape_1,
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
        self._hardware.connect(self._system_message_handler.input_queue, self._selected_animal)
        self._hardware.set_auto_correct_motor_drift(self._behavior.algorithm.auto_correct_motors_drift)
        logger.info("finished connecting hardware")

        return True

    def on_capture_stop(self):
        # logger.verbose("AppModel.on_capture_stop")
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

    def load_configuration(self, location: Optional[str] = None):
        p_location = Path(location or "")
        if not location or not p_location.is_file():
            # Check to see if there is a file in the new default location.  If so, use it.
            p_location = Path(self._preferences.configuration_location)
            p_location.mkdir(parents=True, exist_ok=True)
            logger.info("did not receive explicit configuration file, trying default p_location=%s", p_location)
            configuration = SystemConfiguration.load_default(p_location)
            # Fallback to the old last configuration preference if this device has not converted.
            # TODO - remove this once all devices have migrated.
            if configuration is not None:
                file_path = SystemConfiguration.make_default_yaml_config_path(p_location)
            else:
                logger.info("default not yet in use, trying last configuration")
                file_path = Path(self._preferences.last_configuration)
                if file_path.is_file():
                    configuration = SystemConfiguration.load_yaml_file(file_path)
                if configuration is not None:
                    # Migrate to new default location.
                    configuration.save_default(self._preferences.configuration_location)
        else:
            # Always allow for a custom configuration file if provided.
            logger.info("using explicit configuration %s", location)
            file_path = Path(location)
            configuration: SystemConfiguration = SystemConfiguration.load_yaml_file(file_path)

        if configuration is None:
            configuration = SystemConfiguration()
            logger.info("using default configuration")
        else:
            logger.info("using configuration from %r", file_path.as_posix())

        self._loaded_configuration = configuration

        if (camera := configuration.get_camera(CameraId.Left)) is not None:
            self._left_camera.load_configuration(camera)
        if (camera := configuration.get_camera(CameraId.Right)) is not None:
            self._right_camera.load_configuration(camera)
        if (camera := configuration.get_camera(CameraId.Web)) is not None:
            self._top_camera.load_configuration(camera)

        self.inference.load_configuration(configuration.inference)

        behavior_cfg = configuration.behavior
        self.behavior.load_configuration(behavior_cfg)

        self._analysis.headbar_pressure_monitor.load_configuration(behavior_cfg.headbar_pressure)
        self._analysis.load_cell_monitor.load_configuration(behavior_cfg.load_cell)
        self._analysis.load_cell_tare_monitor.load_configuration(behavior_cfg.auto_tare)
        self._analysis.audio_thrashing_monitor.config = behavior_cfg.audio
        self._analysis.emergency_alarm_monitor.config = behavior_cfg.emergency_alarm
        self._analysis.global_mouse_presence_monitor.config = behavior_cfg.mouse_presence

        self.output_location = configuration.persistence.output_location

        return True

    def save_configuration(self):
        conf = self._create_configuration()
        return conf.save_default(self._preferences.configuration_location)

    def on_activated(self):
        pass

    def on_close(self):
        # logger.verbose("AppModel.on_close")
        self._preferences.save()

        if self._inference is not None:
            self._inference.terminate()

        for camera in self._cameras:
            camera.on_close()

        EventManager.default().close()

        self.hardware.disconnect()
        self._system_message_handler.request_terminate()
        # should we self._message_handler.wait_terminated() ?
        self._system_message_handler.wait_terminated()

        self._multiproc_msg_queue.put(None)
        self._handle_proc_msg_thread.join()

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
            animals = sorted((x for x in loaded if x is not None), key=lambda a: a.name)

        pref_animal = self._preferences.selected_animal
        for animal in animals:
            if pref_animal == animal.name:
                self.selected_animal = animal
                break

        self.animals = animals

    def _trigger_received(self, notification: Notification):
        self._is_recording_trigger = notification.context

        if notification.context and self._project_info is not None:
            now = datetime.now()
            self._save_metadata(now,
                                self._project_info.get_metadata_file(-1, when=now),
                                self._project_info.session)

    def _on_behavior_model_property_changed(self, name: str, new_value, old_value):
        logger.debug("behavior property changed: %s: %s -> %s", name, old_value, new_value)

    def _on_preferences_property_changed(self, name: str, new_value, old_value):
        if name == UserPreferences.SELECTED_ANIMAL:
            for animal in self._animals:
                if animal.name == new_value:
                    self.selected_animal = animal
                    break

    def _on_behavior_algo_property_changed(self, name: str, value, _):
        cur_selected_animal = self._selected_animal
        if cur_selected_animal is None:
            return
        if name == BehaviorAlgoProps.BASELINE_INTENSITY:
            self._selected_animal.baseline_magnet_intensity = value
            self._save_animal_metadata(cur_selected_animal)
        elif name == BehaviorAlgoProps.INTERSESSION_STATE:
            left_cam = self._left_camera
            if value != IntersessionState.idle:
                left_cam.text_overlay = f"Intersession: {value}"
            else:
                left_cam.text_overlay = None

        # elif name == BehaviorAlgoProps.AUTO_CORRECT_MOTOR_DRIFT:
        #     self._hardware.set_auto_correct_motor_drift(value)
        # already handled by SystemMachine

    def _on_hardware_property_changed(self, name: str, value, _):
        cur_selected_animal = self._selected_animal
        if cur_selected_animal is None:
            return
        if name == "set_x":
            cur_selected_animal.pellet_x = value
        elif name == "set_y":
            cur_selected_animal.pellet_y = value
        elif name == "set_z":
            cur_selected_animal.pellet_z = value
        else:
            return
        self._save_animal_metadata(cur_selected_animal)

    def _on_inference_property_changed(self, name: str, new_value, old_value):
        if name == InferenceModel.STATUS:
            algo = self._behavior.algorithm
            new_is_live = new_value == InferenceStatus.live
            left_cam = self._left_camera
            left_cam.display_dots_detection = new_is_live
            self._right_camera.display_dots_detection = new_is_live
            if new_is_live:
                if algo.intersession_state == IntersessionState.idle:
                    left_cam.text_overlay = None
                else:
                    left_cam.text_overlay = f"Intersession: {algo.intersession_state}"
            else:
                if algo.intersession_state == IntersessionState.idle:
                    left_cam.text_overlay = f"Inference: {new_value}"
                else:
                    left_cam.text_overlay = f"Intersession: {algo.intersession_state}"

    def _save_animal_metadata(self, animal):
        if animal is not None:
            animal.to_file(
                Path(self._preferences.animal_location).joinpath(f"{animal.name}.json"))

    def _create_configuration(self) -> SystemConfiguration:
        hardware_configuration = HardwareConfiguration(tunnel_identifier="CAN", pellet_identifier="CAN")

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
        when = project_info.when if project_info.when is not None else datetime.now()
        file_name = project_info.get_metadata_file()
        self._save_metadata(when, file_name, -1)

    def _save_metadata(self, when: datetime, file_name: str, session: int = None):
        when_as_utc = when.astimezone(timezone.utc)
        info = {
            "date": when.strftime("%Y%m%d_%H%M%S"),
            "created": when.timestamp(),
            "createdUtc": when_as_utc.timestamp(),  # same than created
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
                yaml.dump(out, file, Dumper=SystemConfigurationDumper, sort_keys=False)
        except Exception as ex:
            logger.error(ex)
