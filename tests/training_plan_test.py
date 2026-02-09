import contextlib
import copy
import dataclasses
import logging
import threading
import time
from pathlib import Path
from typing import Optional
from unittest import mock

import pytest

from autotrainer.behavior import SystemMachine, InferenceProtocol, BehaviorAlgorithm, TrainingMode, SystemState, \
    IntersessionState
from autotrainer.behavior.pellet import PelletState
from autotrainer.behavior.behavior_algorithm import ShiftXYZBufferHandler
from autotrainer.inference import InferenceStatus
from autotrainer.inference.analysis import IntersessionResponse
from autotrainer.video import CaptureProcessStatus
from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.inference_model import InferenceModel
from tools.acquisition.model.training_plan import get_plan_id
from top_fixtures import MockSystemMachine

this_dir = Path(__file__).parent.resolve()


@pytest.fixture
def inference_model(pose_algo):
    # unused atm
    inference = InferenceModel(pose_algo)
    inference._status = InferenceStatus.live
    yield inference
    inference.terminate()


class TestTrainingPlan(MockSystemMachine):

    @pytest.fixture(autouse=True)
    def training_plans(self, trainer_config_dir):
        # have to copy or link the plan in the config dir given it's "hardcoded" relatively to it for now:
        dst_dir = trainer_config_dir.joinpath("training/protocols")
        dst_dir.mkdir(parents=True, exist_ok=True)
        for p in this_dir.joinpath("training/protocols").glob("*.json"):
            dst_dir.joinpath(p.name).write_bytes(p.read_bytes())

    @pytest.fixture()
    def app_model(self, machine, user_pref, fake_system_msg_handler, system_config, calib_dir, training_plans, sensor_analysis):
        machine._msg_handler = fake_system_msg_handler
        user_pref.save()
        msg_handler = machine._msg_handler
        app_model = AppModel(
            user_pref,
            system_message_handler=msg_handler,
            sensor_analysis=sensor_analysis,
            inference_model=machine._inference,
            calib_dir=calib_dir,
            system_machine=machine,
        )
        app_model.check_diamond_coord_enabled = False
        self._animal = app_model.add_animal("mouse1", select=True)
        try:
            yield app_model
        finally:
            app_model.on_capture_stop()
            app_model.on_close()


    def test_training_plan(self, app_model, user_pref, machine, caplog):
        try:
            self._test_training_plan(app_model, user_pref, machine, caplog)
        finally:
            caplog.set_level(logging.CRITICAL)
            # NB: for some reason the last finally: above in app_model() fixture isn't called
            # when this test case fails for any reason. pytest seems to be stuck in some loop post-analysis code,
            # but before teardown, related to/with tmpdir fixture.. maybe the files we are possibly writing in it
            # are preventing pytest failure completion code to finish and put it in a kind of infinite loop state.
            app_model.on_capture_stop()
            app_model.on_close()

    def _test_training_plan(self, app_model, user_pref, machine, caplog):
        caplog.set_level(logging.DEBUG)  # REQUIRED to ensure we collect/see all the logs we want to assert on,
        # see below

        algo = app_model.behavior.algorithm

        assert app_model.loaded_configuration is None
        assert app_model.load_configuration() is True

        assert algo.intersession_enabled is True  # required
        # NB: do not try change some settings after config is loaded,
        # the loaded parameters/settings (from config file) will be reused/reset with training plan enter.

        shift_xyz_buffer_handler = ShiftXYZBufferHandler(size=2)  # will also check this
        algo.shift_xyz_handler.set_handle_new_shift_xyz(shift_xyz_buffer_handler)

        app_model.training_mode = TrainingMode.AUTOMATIC
        app_model.on_capture_start()

        plan = app_model.get_training_plan_by_id(get_plan_id(app_model.training_plans[0]))
        animal = app_model.selected_animal
        animal.training.current_protocol = plan.plan_id
        app_model.training_plan = plan

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
            self.increment_perf_now()
            assert "Received processed shift xyz: " not in caplog.text
            assert plan.current_phase == plan_start_phase
            caplog.clear()
            self._make_session(app_model, machine, results[session_idx])
            if session_idx == 0:
                assert plan.current_phase == plan_start_phase
                assert plan_start_phase.advance_predicate.evaluate(plan_start_phase, plan._system_context) is False

        # assert plan_start_phase.advance_predicate.evaluate(plan_start_phase, plan._system_context) is True, "phase should be able advance"
        assert plan.current_phase != plan_start_phase, "the phase should have advanced"

        assert "Received processed shift xyz: (1.5, 1.0, 1.0)" in caplog.text, \
            "should be the some avg/mean of the 2 previous sessions, with limits applied"

        assert algo.total_pellet_count == sum(r.food_consumed for r in results)
        assert algo.successful_reaches_total == sum(r.successful_reaches for r in results)
        assert algo.pellets_presented_total == sum(r.pellets_presented for r in results)

        prev_phase = plan.current_phase
        #
        result = IntersessionResponse(
            pellets_presented=3,
            successful_reaches=3,
            food_consumed=3,
            pellet_x=1,
            pellet_y=0.5,
            pellet_z=0.5,
        )
        caplog.clear()
        self._make_session(app_model, machine, result)
        assert plan.current_phase != prev_phase
        #
        prev_phase = plan.current_phase
        result = IntersessionResponse(
            pellets_presented=3,
            successful_reaches=3,
            food_consumed=3,
            pellet_x=1,
            pellet_y=0.5,
            pellet_z=0.5,
        )
        caplog.clear()
        self._make_session(app_model, machine, result)
        assert plan.current_phase == prev_phase, "3rd phase requires Hands near pellet seen < threshold"
        result.pellets_presented = result.successful_reaches = result.food_consumed = 8
        self._make_session(app_model, machine, result, hands_min_dist=0.001)
        # not working yet:
        # assert plan.current_phase != prev_phase, "3rd phase requires Hands near pellet seen < threshold"
        # TODO: TBC... assert phase action(s)

    def _make_session(self, app_model, machine, analysis_result, *,
                      hands_min_dist: Optional[float]=None):
        algo = app_model.behavior.algorithm
        if hands_min_dist is not None:
            algo.pellet_hands_min_distance = hands_min_dist
        #
        pellet_m = self._machine.pellet
        assert pellet_m.state == PelletState.monitoring
        #
        # machine.enter_tunnel(reason="manual")
        algo.update_triangle_seen(True)
        algo.update_pellet_seen(True)
        #
        self._load_cell.is_engaged = True
        #
        assert machine.state == SystemState.tunnel
        algo.update_triangle_seen(True)
        algo.update_pellet_seen(True)
        assert algo.pellet_recently_seen
        assert algo.is_in_session
        assert pellet_m.state == PelletState.monitoring  # still
        # assert algo.can_release_pellet()  some training phase sets cover-pellet-enabled to True..
        #   .. making can_release_pellet() False.
        with contextlib.ExitStack() as stack:
            # to be sure:
            algo.update_triangle_seen(True)
            algo.update_mouse_seen(True)
            algo.update_pellet_seen(True)
            stack.enter_context(self.mock_perform_segmentation())
            stack.enter_context(self.mock_perform_detection())
            assert pellet_m.state == PelletState.monitoring  # still
            self._load_cell.is_engaged = False  # exit tunnel
            assert not algo.is_in_session
            assert algo.system_state == SystemState.intersession
            assert algo.intersession_state == IntersessionState.segmentation
            assert pellet_m.state == PelletState.retract  # Retract !!
            self.mock_complete_segmentation(True)
            assert algo.system_state == SystemState.intersession
            assert algo.intersession_state == IntersessionState.detection
            machine._inference.detection_result_ready(analysis_result)
            self.mock_complete_detection(True)
            assert algo.intersession_state == IntersessionState.idle
            assert algo.system_state == SystemState.cage
            assert pellet_m.state == PelletState.retract  # still

        assert not algo.is_in_session

        assert pellet_m.state == PelletState.retract  # still
        # NB: at least one of the training phase is setting pellet-delivery-enabled to False, reset it here:
        algo.pellet_delivery_enabled = True
        # so that pellet-send will be allowed with ack of previous retract:

        self.mock_pellet_ack()  # for retract
        assert self.pellet_state_trans[-2:] == [PelletState.sending, PelletState.monitoring]
        self.mock_pellet_ack()  # for send

        algo.capture_status = CaptureProcessStatus.RUNNING
        assert machine.state == SystemState.cage  # still ofc.

        self.increment_perf_now(1)
