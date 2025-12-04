import contextlib
import copy
import logging
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from autotrainer.behavior import SystemMachine, InferenceProtocol, BehaviorAlgorithm, TrainingMode, SystemState
from autotrainer.behavior.behavior_algorithm import ShiftXYZBufferHandler
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
def training_plans():
    plans = load_training_plans(this_dir.joinpath("training/protocols"))
    return list(plans.values())


@pytest.fixture()
def plan(training_plans):
    return copy.deepcopy(training_plans[0])


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
        app_model.training_plans = [plan]
        try:
            yield app_model
        finally:
            app_model.on_capture_stop()
            app_model.on_close()

    def test_training_plan(self, app_model, user_pref, machine, plan, caplog):
        try:
            self._test_training_plan(app_model, user_pref, machine, plan, caplog)
        finally:
            # NB: for some reason the last finally: above in app_model() fixture isn't called
            # when this test case fails for any reason. pytest seems to be stuck in some loop post-analysis code,
            # but before teardown, related to/with tmpdir fixture.. maybe the files we are possibly writing in it
            # are preventing pytest failure completion code to finish and put it in a kind of infinite loop state.
            app_model.on_capture_stop()
            app_model.on_close()

    def _test_training_plan(self, app_model, user_pref, machine, plan, caplog):
        caplog.set_level(logging.DEBUG)  # REQUIRED to ensure we collect/see all the logs we want to assert on,
        # see below

        algo = app_model.behavior.algorithm

        assert app_model.load_configuration() is True

        shift_xyz_buffer_handler = ShiftXYZBufferHandler(size=2)  # will also check this
        algo.shift_xyz_handler.set_handle_new_shift_xyz(shift_xyz_buffer_handler)
        algo.intersession_enabled = True
        app_model.training_mode = TrainingMode.AUTOMATIC
        app_model.training_plan = plan  # this also sets it as current_protocol on current selected animal
        app_model.on_capture_start()

        plan_start_phase = plan.current_phase

        assert plan_start_phase.advance_predicate.evaluate(plan_start_phase, plan._system_context) is False
        # NB:
        results = [
            IntersessionResponse(
                pellets_presented=3,
                successful_reaches=2,
                food_consumed=1,
                pellet_x=1,
                pellet_y=0.5,
                pellet_z=0.5,
            ),
            IntersessionResponse(
                pellets_presented=3,
                successful_reaches=2,
                food_consumed=2,
                pellet_x=2,
                pellet_y=-0.5,
                pellet_z=-1,
            ),
        ]

        for session_idx in range(2):
            assert "Received processed shift xyz: " not in caplog.text
            assert plan.current_phase == plan_start_phase
            caplog.clear()
            self._make_session(app_model, machine, results[session_idx])
            if session_idx == 0:
                assert plan.current_phase == plan_start_phase
                assert plan_start_phase.advance_predicate.evaluate(plan_start_phase, plan._system_context) is False

        assert plan_start_phase.advance_predicate.evaluate(plan_start_phase, plan._system_context) is True
        assert plan.current_phase != plan_start_phase, "the phase should have advanced"

        assert "Received processed shift xyz: (1.5, 0.0, -0.2)" in caplog.text, \
            "should be the avg/mean of the 2 previous sessions"

        assert algo.total_pellet_count == sum(r.food_consumed for r in results)
        assert algo.successful_reaches_total == sum(r.successful_reaches for r in results)
        assert algo.pellets_presented_total == sum(r.pellets_presented for r in results)

        prev_phase = plan.current_phase
        #
        results = [
            IntersessionResponse(
                pellets_presented=3,
                successful_reaches=3,
                food_consumed=3,
                pellet_x=1,
                pellet_y=0.5,
                pellet_z=0.5,
            ),
        ]
        caplog.clear()
        self._make_session(app_model, machine, results[0])
        assert plan.current_phase != prev_phase
        # TODO: TBC... assert phase action(s)

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

