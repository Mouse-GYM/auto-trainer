import copy
import threading
from pathlib import Path
from unittest import mock

import pytest

from autotrainer.behavior import SystemMachine, InferenceProtocol, BehaviorAlgorithm, TrainingMode
from autotrainer.core import AnimalSubject
from autotrainer.device import MotorConfigurationFile
from autotrainer.inference import InferenceStatus
from autotrainer.video import CaptureProcessStatus
from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.inference_model import InferenceModel
from tools.acquisition.model.training_plan import load_training_plans
from top_fixtures import MockSystemMachine

this_dir = Path(__file__).parent.resolve()


@pytest.fixture
def inference_model(pose_algo):
    inference = InferenceModel(pose_algo)
    inference._status = InferenceStatus.live
    yield inference
    inference.terminate()
    # inference.terminate()


@pytest.fixture(scope="session")
def _plan():
    plans = load_training_plans(this_dir.joinpath("training/protocols"))
    return plans[0]


@pytest.fixture()
def plan(_plan):
    return copy.deepcopy(_plan)


@pytest.fixture
def machine2(project_info, tunnel_device, pellet_device, inference_model, sensor_analysis):
    # prevents some test to fail due to handling function in dedicated thread
    BehaviorAlgorithm._no_handler_thread = True
    #
    def check_pres_missing(delay, func):
        m = mock.create_autospec(threading.Timer)
        return m
    with mock.patch(f"{SystemMachine.__module__}._check_missing_timer", new=check_pres_missing):
        machine = SystemMachine(
            tunnel_device=tunnel_device,
            pellet_device=pellet_device,
            analysis=sensor_analysis,
            inference=inference_model,
            project_info=project_info,
        )
        machine.algorithm.capture_status = CaptureProcessStatus.RUNNING
        machine.algorithm.pellet_hand_uncover_distance = None  # disabled
        yield machine


class TestTrainingPlan(MockSystemMachine):

    def setup_method(self, test_method):
        pass

    @pytest.fixture()
    def app_model(self, machine, user_pref, system_msg_handler, system_config, plan):
        machine._msg_handler = system_msg_handler
        user_pref.save()
        msg_handler = machine._msg_handler
        app_model = AppModel(
            user_pref,
            system_message_handler=msg_handler,
            sensor_analysis=msg_handler.analysis,
            inference_model=machine._inference,
        )
        self._animal = app_model.add_animal("mouse1", select=True)
        app_model.training_plans.append(plan)
        yield app_model
        app_model.on_capture_stop()
        app_model.on_close()

    def test_training_plan(self, app_model, user_pref, machine, plan):
        print(app_model)
        algo = app_model.behavior.algorithm
        animal = self._animal
        assert app_model.load_configuration() is True
        algo.intersession_enabled = True
        app_model.on_capture_start()
        app_model.training_mode = TrainingMode.MANUAL_AND_PROTOCOL
        app_model.training_plan = plan
        print(app_model)
        machine.enter_tunnel(reason="manual")
        self.mock_pose_response(pellet_seen=True, mouse_seen=True, triangle_seen=True)
        machine.exit_tunnel(reason="manual")
        # app_model.behavior.system_machine.intersession.
        assert algo.pellet_recently_seen
