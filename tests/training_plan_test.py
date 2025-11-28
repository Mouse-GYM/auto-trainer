import contextlib
import copy
import threading
from pathlib import Path
from unittest import mock

import pytest

from autotrainer.behavior import SystemMachine, InferenceProtocol, BehaviorAlgorithm, TrainingMode, SystemState
from autotrainer.core import AnimalSubject
from autotrainer.device import MotorConfigurationFile
from autotrainer.inference import InferenceStatus
from autotrainer.inference.analysis import IntersessionResponse
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


class TestTrainingPlan(MockSystemMachine):

    def setup_method(self, test_method):
        pass

    @pytest.fixture()
    def app_model(self, machine, user_pref, system_msg_handler, system_config, plan, calib_dir):
        machine._msg_handler = system_msg_handler
        user_pref.save()
        msg_handler = machine._msg_handler
        app_model = AppModel(
            user_pref,
            system_message_handler=msg_handler,
            sensor_analysis=msg_handler.analysis,
            inference_model=machine._inference,
            calib_dir=calib_dir,
            system_machine=machine,
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
        # animal.training.current_protocol =
        assert app_model.load_configuration() is True
        algo.intersession_enabled = True
        app_model.training_mode = TrainingMode.MANUAL_AND_PROTOCOL
        app_model.training_plan = plan
        app_model.on_capture_start()
        print(app_model)
        for _ in range(2):
            result = IntersessionResponse(
                food_consumed=2,
                pellet_x=1,
                pellets_presented=4,
                successful_reaches=3,
            )
            self._make_session(app_model, machine, result)

        assert algo.total_pellet_count == 2 * result.food_consumed
        assert algo.successful_reaches_total == 2 * result.successful_reaches

    def _make_session(self, app_model, machine, analysis_result):
        algo = app_model.behavior.algorithm
        machine.enter_tunnel(reason="manual")
        # self.make_load_cell_active()
        assert machine.state == SystemState.tunnel
        self.make_recording_aged_enough()
        self.mock_pose_response(pellet_seen=True, mouse_seen=True, triangle_seen=True)
        assert algo.pellet_recently_seen
        # self.make_load_cell_inactive()
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.mock_perform_segmentation())
            machine.exit_tunnel(reason="manual")
            stack.enter_context(self.mock_perform_detection())
            self.mock_complete_segmentation(True)
            machine._inference.detection_result_ready(analysis_result)
            self.mock_complete_detection(True)
            assert machine.state == SystemState.cage

        app_model.hardware.send_home()

