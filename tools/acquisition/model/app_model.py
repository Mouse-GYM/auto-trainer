import dataclasses
import copy
import enum
import json
import logging
import math
import multiprocessing
import pickle
import queue
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Callable, Any

import yaml

from autotrainer.core.analysis import calibration_FLIR
from autotrainer.core import (ObservableObject, EventManager, SystemMessageHandler, SystemConfiguration,
                              CameraId, PersistenceConfiguration, HardwareConfiguration, Notification,
                              NotificationCenter, TriggerNotification, SystemStatusMessageKind, SensorAnalysis,
                              Offset3DTuple)
from autotrainer.core import FixedArrayMultiQueue
from autotrainer.core import ProjectInfo
from autotrainer.core import AnimalSubject
from autotrainer.core.configuration import SystemConfigurationDumper
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import get_mp_ctx, make_daemon_timer

from autotrainer.core.project.project_info import DATE_FORMAT, DATE_TIME_FORMAT

from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.core.analysis.config import load_calib_stereo_params

from autotrainer.video import CaptureProcessStatus
from autotrainer.inference import PoseAlgorithm, InferenceStatus

from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.behavior import IntersessionState, BehaviorAlgorithm, TrainingMode, InferenceProtocol, SystemMachine

from autotrainer.training import TrainingPlan, TrainingPhase

from tools.acquisition.model.hardware_model import HardwareModel
from tools.acquisition.model.inference_model import InferenceModel
from tools.acquisition.model.behavior_model import BehaviorModel
from tools.acquisition.model.project_dependent_protocol import ProjectDependentProtol
from tools.acquisition.model.training_plan import load_training_plans
from tools.acquisition.model.user_preferences import UserPreferences
from tools.acquisition.model.video_capture_model import VideoCaptureModel

logger = get_verbose_logger(__name__)


# allow be patched from tests
_recording_age_enough_timer = make_daemon_timer


def _failed_camera_template(name: str, error: str):
    return f"Failed to start capture process for camera {name}:\n\t{error}\nPlease check all connections and settings."


class AppModel(ObservableObject):

    configuration_loaded_event: Callable[[SystemConfiguration], None]
    on_error: Callable[[str, str], None]

    class Props(str, enum.Enum):
        ANIMALS = "animals"
        SELECTED_ANIMAL = "selected_animal"
        OUTPUT_LOCATION = "output_location"
        ANIMAL_NAME = "animal_name"
        NOTES = "notes"
        TRAINING_MODE = 'training_mode'
        TRAINING_PLAN = "training_plan"
        TRAINING_PHASE = "training_plan.current_phase"

    def __init__(
        self,
        preferences: UserPreferences,
        app_version: str = "",
        *,
        calib_dir: Optional[Path] = None,
        sensor_analysis: Optional[SensorAnalysis] = None,
        inference_model: Optional[InferenceProtocol] = None,
        system_message_handler: Optional[SystemMessageHandler] = None,
        system_machine: Optional[SystemMachine] = None,
    ):
        super().__init__(('on_error', 'configuration_loaded_event'))

        # using a shared process manager,
        # this allows to put shared values, created via the manager, to any multiprocess shared queue, notably.
        self._mp_manager = multiprocessing.get_context("spawn").Manager()
        # otherwise (new) shared values can only be inherited from newly spawned sub-process(es) and not from already
        # existing sub-process(es).

        self._preferences = preferences
        self._loaded_configuration: Optional[SystemConfiguration] = None

        self._app_version = app_version

        self._training_mode = TrainingMode.MANUAL
        self._training_plan: Optional[TrainingPlan] = None
        self._training_plan_animal: Optional[AnimalSubject] = None

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
        sensor_analysis = self._analysis = SensorAnalysis(topcam_presence=self._top_camera_presence_detection) if sensor_analysis is None else sensor_analysis
        #
        self._system_message_handler = SystemMessageHandler(self._system_message_queue,
                                                            sensor_analysis=sensor_analysis) if system_message_handler is None else system_message_handler
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

        self._inference = InferenceModel(self._pose_algorithm, calib_dir=calib_dir) if inference_model is None else inference_model

        #

        self._training_plans: List[TrainingPlan] = []
        self._training_plan_by_plan_id: Dict[str, TrainingPlan] = {}

        self._behavior = BehaviorModel(
            self._system_message_handler, self._analysis, self._hardware, self._inference,
            topcam_presence=self._top_camera_presence_detection,
            system_machine=system_machine,
        )

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
        self._animal_by_id: Dict[str, AnimalSubject] = {}

        self._selected_animal: Optional[AnimalSubject] = None
        self._attached_plan: Optional[TrainingPlan] = None
        self._attached_animal: Optional[AnimalSubject] = None

        NotificationCenter.default_center().add_observer(TriggerNotification.CAPTURE_ID, self._trigger_received)

        self._hardware.property_changed += self._on_hardware_property_changed
        self._behavior.algorithm.property_changed += self._on_behavior_algo_property_changed
        preferences.property_changed += self._on_preferences_property_changed
        self._inference.property_changed += self._on_inference_property_changed

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
    def animals(self) -> List[AnimalSubject]:
        return self._animals

    @animals.setter
    def animals(self, value: List[AnimalSubject]):
        self._animals = self._on_property_changed(self.Props.ANIMALS, value, self._animals)

    def get_animal_by_id(self, animal_id) -> Optional[AnimalSubject]:
        for animal in self._animals:
            if animal.id == animal_id:
                return animal
        return None

    @property
    def selected_animal(self) -> Optional[AnimalSubject]:
        return self._selected_animal

    @selected_animal.setter
    def selected_animal(self, animal: Optional[AnimalSubject]):
        prev, self._selected_animal = self._selected_animal, animal
        if animal == prev:
            return
        self._detach_training_plan()  # always
        logger.debug("updating animal to %s (prev=%s)", animal, prev)
        if prev is not None:
            self._save_animal_metadata(prev, sender="selected_animal_detach")  # in case of
        self.property_changed(self.Props.ANIMAL_NAME, *(
            ("(none)", "(none)") if animal is None
            else (animal.name, self.animal_name)
        ))
        if animal is None:
            self.training_plan = None
        else:
            logger.debug("animal pellet=%s is_dcs=%s",
                         (animal.pellet_x, animal.pellet_y, animal.pellet_z), animal.is_pellet_dcs)
            algo = self._behavior.algorithm
            algo.baseline_intensity = animal.baseline_magnet_intensity
            algo.reset_selected_animal_counts(animal)
            if self._training_mode == TrainingMode.MANUAL:
                # only set animal base position if manual training mode
                self._set_animal_base_positions_and_send_to_deliver(animal)
            self.training_plan = self.get_training_plan_by_id(animal.training.current_protocol)

        self._on_property_changed(self.Props.SELECTED_ANIMAL, animal, prev)
        self._preferences.selected_animal = "" if animal is None else animal.name
        logger.success("Switched to animal %s", animal)

    @property
    def training_mode(self):
        return self._training_mode

    @training_mode.setter
    def training_mode(self, value):
        prev, self._training_mode = self._training_mode, value
        if prev == value:
            return
        if value == TrainingMode.MANUAL:
            self._detach_training_plan()
        else:
            plan = self._training_plan
            if plan is not None and self._attached_plan is None:
                self._attach_training_plan(plan)
        self._on_property_changed(self.Props.TRAINING_MODE, value, prev)

    @property
    def attached_plan(self) -> Optional[TrainingPlan]:
        return self._attached_plan

    @property
    def training_plan(self) -> Optional[TrainingPlan]:
        return self._training_plan

    @training_plan.setter
    def training_plan(self, value: Optional[TrainingPlan]):
        animal = self._selected_animal
        prev, self._training_plan = self._training_plan, value
        if prev == value and self._training_plan_animal == animal:
            return
        self._training_plan_animal = animal
        if animal is not None:
            self._detach_training_plan()
            new_plan_id = None if value is None else value.plan_id
            prev_plan_id, animal.training.current_protocol = animal.training.current_protocol, new_plan_id
            if new_plan_id != prev_plan_id:
                self._save_animal_metadata(animal, sender="animal_current_plan_changed")
        if value is None:
            self._detach_training_plan()  # always
        elif animal is not None:
            if self._training_mode != TrainingMode.MANUAL:
                self._attach_training_plan(value)
        self._on_property_changed(self.Props.TRAINING_PLAN, value, prev)

    @property
    def output_location(self) -> str:
        return self._output_location

    @output_location.setter
    def output_location(self, value: str):
        if self._output_location == value:
            return
        old_value = self._output_location
        self._output_location = value
        self.property_changed(self.Props.OUTPUT_LOCATION, value, old_value)

    @property
    def animal_name(self) -> str:
        animal = self._selected_animal
        return "(none)" if animal is None else animal.name

    @property
    def notes(self) -> str:
        return self._notes

    @notes.setter
    def notes(self, value: str):
        self._notes = self._on_property_changed(self.Props.NOTES, value, self._notes)

    @property
    def training_plans(self) -> List[TrainingPlan]:
        return self._training_plans

    def get_training_plan_by_id(self, plan_id: Optional[str]) -> Optional[TrainingPlan]:
        if plan_id is None:
            return None
        attached = self._attached_plan
        if attached is not None and attached.plan_id == plan_id:
            logger.debug("get_training_plan_by_id: reusing attached: %s", attached)
            return attached
        plan = self._training_plan_by_plan_id.get(plan_id)
        if plan is None:
            logger.warning("Unknown plan_id: %s", plan_id)
            return None
        # plan = copy.deepcopy(plan)  # always, so that different mouses won't share same plan instance
        animal = self._selected_animal
        if animal is not None:
            prog = animal.training.get_plan_progress(plan.plan_id)
            if prog is not None:
                logger.debug("%s: deserializing plan progress: %s", animal, prog)
                plan.deserialize_progress(prog)
        return plan

    def _attach_training_plan(self, plan: TrainingPlan):
        algo = self._behavior.algorithm
        animal = self._selected_animal
        assert animal is not None
        attached = self._attached_plan
        if attached is not None:
            if attached.plan_id == plan.plan_id and animal == self._attached_animal:
                logger.verbose("Plan %s already attached", plan.plan_id)
                return
            self._detach_training_plan()
        logger.success("Animal %s: attaching plan %s (%s) ..", animal, plan.plan_id, hex(id(plan)))
        plan.is_automatic = self._training_mode == TrainingMode.AUTOMATIC
        plan.behavior_algorithm = algo
        plan.pellet_device = self._hardware
        plan.tunnel_device = self._hardware
        self._attached_plan = plan
        self._attached_animal = animal
        plan.property_changed += self._on_training_plan_property_changed  # first, to be sure get everything
        plan.resume()

    def _detach_training_plan(self):
        plan = self._attached_plan
        if plan is None:
            return
        prog = plan.serialize_progress()
        animal = self._attached_animal
        assert animal is not None
        logger.notice("%s: detaching from plan %s (%s)", animal.name, plan.plan_id, hex(id(plan)))
        animal.training.set_plan_progress(plan.plan_id, prog)
        plan.property_changed -= self._on_training_plan_property_changed  # last
        plan.behavior_algorithm = plan.pellet_device = plan.tunnel_device = None
        self._attached_plan = None
        self._attached_animal = None
        self._save_animal_metadata(animal, sender="detach_plan")
    #

    def add_animal(self, name: str, select: bool = False):
        if not name or len(name) == 0:
            return

        matching_animals = [x for x in self._animals if x.name == name]

        if len(matching_animals) == 0:
            logger.info("Adding new animal name=%s", name)
            animal = AnimalSubject(name=name)
            self._save_animal_metadata(animal)

            # Ensure property change events for listeners
            animals = self._animals
            animals.append(animal)
            self._animals = None
            self.animals = animals
        else:
            animal = matching_animals[0]

        if select:
            self.selected_animal = animal
        return animal

    def on_capture_start(self) -> bool:

        analysis = self._analysis

        # first:
        self._behavior.system_machine.intersession.reset_to_idle()
        # to ensure clear state on start, previous segmentation/detection could have fails,
        # and left behind their context.

        # also:
        self._project_info = ProjectInfo(
            root=self.output_location,
            device_id=self._preferences.serial_number,
            ensure_exists=True,
            camera_1=self._left_camera.name,
            camera_2=self._right_camera.name,
            mp_manager=self._mp_manager,  # required,
            # so to have shared values that can be put to multiprocess queue.
            # The active ProjectInfo must effectively be shared across all processes/threads.
            # and/but some of the sub-processes are started early (and kept alive after),
            # so using mp manager allows to put this ProjectInfo instance, along the shared values created via this
            # manager, to any of these already alive sub-processes, via a multiprocess.Queue().put() call/transfer.
        )

        # Now put the new project info to all "models" :
        for model in self._models:
            model.project = self._project_info

        analysis.project_info = self._project_info

        self._behavior.on_prepare_capture()

        self._inference_queue = None
        left_cam = self._left_camera
        right_cam = self._right_camera
        top_cam = self._top_camera

        if self._inference.is_enabled:
            shape_1 = left_cam.shape
            shape_2 = right_cam.shape
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
        else:
            self._inference_queue = None

        did_start = left_cam.on_prepare_capture(self._inference_queue)

        if not did_start:
            self.on_error("Camera Process Failed",
                          _failed_camera_template(left_cam.name, left_cam.last_error))

        if did_start:
            did_start = did_start and right_cam.on_prepare_capture(self._inference_queue)
            if not did_start:
                self.on_error("Camera Process Failed",
                              _failed_camera_template(right_cam.name, right_cam.last_error))

        if did_start:
            did_start = did_start and top_cam.on_prepare_capture()
            if not did_start:
                self.on_error("Camera Process Failed",
                              _failed_camera_template(top_cam.name, top_cam.last_error))

        if not did_start:
            logger.error("failed to start all subprocesses")
            self.on_capture_stop()
            return False

        self._save_project_metadata(self._project_info)

        if self._inference.is_enabled:
            self._inference.start(self._inference_queue)

        for camera in self._cameras:
            if camera.is_primary:
                camera.on_capture_start()

        for camera in self._cameras:
            if not camera.is_primary:
                camera.on_capture_start()

        logger.debug("connecting hardware ...")
        self._hardware.connect(self._system_message_handler.input_queue)
        self._hardware.set_auto_correct_motor_drift(self._behavior.algorithm.auto_correct_motors_drift)
        logger.info("finished connecting hardware")

        algo = self._behavior.algorithm

        if not algo.algo_paused:
            analysis.start()

        animal = self._selected_animal
        plan = (
            None if (animal is None or animal.training.current_protocol is None)
            else self.get_training_plan_by_id(animal.training.current_protocol)
        )
        if self._training_mode == TrainingMode.MANUAL or animal is None:
            # logger.notice("training mode is MANUAL or animal is none")
            # forcing manual so:
            self.training_mode = TrainingMode.MANUAL
        else:
            if plan is not None and self._training_mode != TrainingMode.MANUAL:
                self._attach_training_plan(plan)

        if self._attached_animal is None and animal is not None:
            self._set_animal_base_positions_and_send_to_deliver(animal)

        return True

    def on_capture_stop(self):
        logger.debug("AppModel.on_capture_stop")

        self._detach_training_plan()  # always

        analysis = self._analysis
        analysis.stop()

        self._inference.stop()
        self.hardware.disconnect()

        for camera in self._cameras:
            if not camera.is_primary:
                logger.verbose("notifying end to %s", camera.name)
                camera.on_capture_notify_end()

        time.sleep(0.01)

        for camera in self._cameras:
            if camera.is_primary:
                logger.verbose("notifying end to %s", camera.name)
                camera.on_capture_notify_end()

        for camera in self._cameras:
            if not camera.is_primary:
                logger.verbose("stopping capture to %s", camera.name)
                camera.on_capture_stop()

        for camera in self._cameras:
            if camera.is_primary:
                logger.verbose("stopping capture to %s", camera.name)
                camera.on_capture_stop()

        analysis.project_info = None

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

        if (camera := configuration.get_camera(CameraId.Left)) is not None:
            self._left_camera.load_configuration(camera)
        if (camera := configuration.get_camera(CameraId.Right)) is not None:
            self._right_camera.load_configuration(camera)
        if (camera := configuration.get_camera(CameraId.Web)) is not None:
            camera.record_prebuffer_duration = 0  # force for now ; so to not keep a buffer for nothing in topcam
            self._top_camera.load_configuration(camera)

        self.inference.load_configuration(configuration.inference)

        behavior_cfg = configuration.behavior
        self.behavior.load_configuration(behavior_cfg)

        self._analysis.headbar_pressure_monitor.load_configuration(behavior_cfg.headbar_pressure)
        self._analysis.load_cell_monitor.load_configuration(behavior_cfg.load_cell)
        self._analysis.load_cell_tare_monitor.load_configuration(behavior_cfg.auto_tare)
        self._analysis.audio_thrashing_monitor.config = behavior_cfg.audio
        self._analysis.emergency_alarm_monitor.config = behavior_cfg.emergency_alarm
        self._analysis.global_animal_presence_monitor.config = behavior_cfg.global_animal_presence
        self._analysis.external_doors_monitor.config = behavior_cfg.external_doors

        self.output_location = configuration.persistence.output_location

        # only at the end:
        self._loaded_configuration = configuration

        self._training_plans = load_training_plans(
            Path(self._preferences.configuration_location).joinpath("training/protocols"))
        self._training_plan_by_plan_id = {
            plan.plan_id: plan
            for idx, plan in enumerate(self._training_plans)
        }

        # and:
        self._load_animals()

        self.configuration_loaded_event(configuration)

        return True

    def save_configuration(self):
        if self._loaded_configuration is None:
            # do not save if loaded_config is still None, which signify the load configuration failed,
            # so we won't overwrite the (currently) bad user config file with one having all defaults.
            return
        loc = self._preferences.configuration_location
        logger.info("Saving configuration to %s", loc)
        conf = self._create_configuration()
        conf.save_default(loc)

    def on_activated(self):
        pass

    def on_close(self):
        logger.debug("AppModel.on_close")
        self.on_capture_stop()  # ensure

        self._preferences.save()

        if self._inference is not None:
            self._inference.terminate()

        analysis = self._analysis
        analysis.stop()

        for camera in self._cameras:
            camera.on_close()

        EventManager.default().close()

        self.hardware.disconnect()

        self._system_message_handler.request_terminate()
        self._system_message_handler.wait_terminated()

        logger.debug("Putting None to process messages thread")
        self._multiproc_msg_queue.put(None)

        logger.debug("Joining process messages thread")
        self._handle_proc_msg_thread.join(5)
        if self._handle_proc_msg_thread.is_alive():
            logger.warning("Handle process messages thread still alive ; closing queue")
        # self._multiproc_msg_queue.close()
        # do not close to allow multiple on_close() calls.

        # somehow if many AppModel are created (like in test cases), this makes the ones following an on_close on any
        # of them to fails hardly. MP manager looks be a singleton per python process so it might be smth related.
        # commenting to prevent this bad effect for now.
        # TODO: could investigate to see if can close it or not, might be at cli main() level is where to do
        # mp_mgr = self._mp_manager
        # logger.debug("shutting down multiprocess manager %s", mp_mgr)
        # mp_mgr.shutdown()
        # mp_mgr.join()


        self.save_configuration()

    def _load_animals(self):
        animals = []

        if self._preferences.animal_location is None or len(self._preferences.animal_location) == 0:
            default_location = Path.home().joinpath("Documents/RawDataLocal/Animals")

            try:
                default_location.mkdir(parents=True)
                self._preferences.animal_location = str(default_location)
            except Exception as e:
                logger.error(f"Failed to create default animal location {default_location}: {e}")
                return

        path = Path(self._preferences.animal_location)

        if path.exists() and path.is_dir():
            files = [x.name for x in path.glob("*.json")]
            loaded = [AnimalSubject.from_file(str(path.joinpath(x))) for x in files]
            animals = sorted((x for x in loaded if x is not None), key=lambda a: a.name)

        pref_animal = self._preferences.selected_animal
        for animal in animals:
            if pref_animal == animal.name:
                self.selected_animal = animal
                break

        if self.selected_animal is None and len(animals) > 0:
            self.selected_animal = animals[0]

        self.animals = animals

    def _trigger_received(self, notification: Notification):
        self._is_recording_trigger = notification.context

        if notification.context and self._project_info is not None:
            now = datetime.now()
            self._save_metadata(now,
                                self._project_info.get_metadata_file(-1, when=now),
                                self._project_info.session)

    def _update_status_text_overlay(self):
        parts = []
        cur_inf_status = self._inference.status
        is_running = cur_inf_status in {InferenceStatus.live, InferenceStatus.intersession}
        if not is_running:
            parts.append(f"Inference: {cur_inf_status}")
        cur_inter_state = self._behavior.system_machine.intersession.state
        if cur_inter_state != IntersessionState.idle:
            parts.append(f"Intersession: {cur_inter_state}")
        self._left_camera.text_overlay = None if len(parts) == 0 else "\n".join(parts)

    def _set_animal_base_positions_and_send_to_deliver(self, animal: AnimalSubject):
        xyz = Offset3DTuple(animal.pellet_x, animal.pellet_y, animal.pellet_z)
        logger.verbose("Setting animal base positions and sending to %s is_pellet_dcs=%s",
                       xyz.humanize(n_digits=1), animal.is_pellet_dcs)
        algo = self._behavior.algorithm
        cfg = algo.diamond_triangle_config
        if cfg is None and animal.is_pellet_dcs:
            logger.warning("loaded animal with pellet DCS, but no diamond-triangle config, forcing to 0")
            animal.is_pellet_dcs = False
            animal.pellet_x = animal.pellet_y = animal.pellet_z = 0
            self._save_animal_metadata(animal, backup_previous=True, sender="selected_animal")
        if animal.is_pellet_dcs:
            assert cfg is not None
            _xyz = xyz
            xyz = cfg.diamond_to_motor(xyz)
            logger.verbose("converted %s to %s", _xyz.humanize(), xyz.humanize())
        else:
            if cfg is not None:
                assert not animal.is_pellet_dcs
                save_xyz = cfg.motor_to_diamond(xyz)
                logger.notice("Converting animal pellet XYZ to DCS: %s -> %s",
                              xyz.humanize(), save_xyz.humanize())
                animal.pellet_x = save_xyz.x
                animal.pellet_y = save_xyz.y
                animal.pellet_z = save_xyz.z
                animal.is_pellet_dcs = True
                self._save_animal_metadata(animal, backup_previous=True, sender="selected_animal")
        hardware = self._hardware
        hardware.delay(0.5)
        hardware.update_head_magnet_intensity(animal.baseline_magnet_intensity)
        hardware.set_x(xyz.x)
        hardware.set_y(xyz.y)
        hardware.set_z(xyz.z)
        hardware.send_pellet()

    def _on_preferences_property_changed(self, name: str, new_value, old_value):
        if name == UserPreferences.SELECTED_ANIMAL:
            for animal in self._animals:
                if animal.name == new_value:
                    self.selected_animal = animal
                    break

    def _on_behavior_algo_property_changed(self, name: str, value, _):
        if name == BehaviorAlgoProps.INTERSESSION_STATE:
            self._update_status_text_overlay()
            return
        #
        animal = self._selected_animal
        if animal is None:
            return
        #
        if name == BehaviorAlgoProps.BASELINE_INTENSITY:
            prev, animal.baseline_magnet_intensity = animal.baseline_magnet_intensity, value
            if value != prev:
                self._save_animal_metadata(animal, sender="baseline_magnet_intensity")
        # elif name == BehaviorAlgoProps.AUTO_CORRECT_MOTOR_DRIFT:
        #     self._hardware.set_auto_correct_motor_drift(value)
        # already handled by SystemMachine

    def _on_hardware_property_changed(self, name: str, value, _):
        animal = self._selected_animal
        if animal is None:
            return
        if name in {'set_x', 'set_y', 'set_z'}:
            # only when manual:
            if self._training_mode != TrainingMode.MANUAL:
                return
            hardware = self._hardware
            coord = name[-1]
            coord_idx = "xyz".index(coord)
            # prevent NaN if hardware has not yet reported any send_x :
            t = [hardware.send_x, hardware.send_y, hardware.send_z]
            t[coord_idx] = value
            if any((math.isnan(v) or v is None) for v in t):
                logger.verbose("hardware set_xyz has NaN/None still: %s", t)
                return
            changed = False
            xyz = orig_xyz = Offset3DTuple(*t)
            cfg = self._behavior.algorithm.diamond_triangle_config
            if cfg is None:
                changed |= animal.is_pellet_dcs
                animal.is_pellet_dcs = False
            else:
                changed |= not animal.is_pellet_dcs
                animal.is_pellet_dcs = True
                xyz = cfg.motor_to_diamond(xyz)
            pellet_dcs_changed = changed
            # only update same animal coordinate,
            # we are supposing the all same axis in the 2 coordinate system are parallel :
            if coord == 'x':
                prev, animal.pellet_x = animal.pellet_x, xyz.x
                new = xyz.x
            elif coord == 'y':
                prev, animal.pellet_y = animal.pellet_y, xyz.y
                new = xyz.y
            else:
                assert coord == 'z'
                prev, animal.pellet_z = animal.pellet_z, xyz.z
                new = xyz.z
            changed |= new != prev
            if changed:
                self._save_animal_metadata(animal, sender=f"hardware_{name}", backup_previous=pellet_dcs_changed)

    def _on_inference_property_changed(self, name: str, new_value, _):
        if name == InferenceModel.STATUS:
            new_is_live = new_value == InferenceStatus.live
            left_cam = self._left_camera
            left_cam.display_dots_detection = new_is_live
            self._right_camera.display_dots_detection = new_is_live
            self._update_status_text_overlay()

    def _on_training_plan_property_changed(self, name, value, _):
        if name == "current_phase":
            if value is not None:
                assert isinstance(value, TrainingPhase)
            self.property_changed(self.Props.TRAINING_PHASE, value, _)

    def _save_animal_metadata(self, animal: AnimalSubject, *, backup_previous: bool = False, sender: str="na"):
        prev_animals = self._animals  # in case _animals content is copied, we reset it to current animal
        for idx, prev_animal in enumerate(prev_animals):
            if prev_animal.id == animal.id:
                prev_animals[idx] = animal
        dst = Path(self._preferences.animal_location).joinpath(f"{animal.name}.json")
        logger.verbose("Saving %s to %s ; sender=%s", animal, dst, sender)
        if backup_previous:
            if dst.exists():
                now = datetime.now()
                dst.with_suffix(f'.bak-{now.strftime(DATE_TIME_FORMAT)}').write_bytes(dst.read_bytes())
        animal.to_file(dst)

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
        info: Dict[str, Any] = {
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
