import dataclasses
import random
import threading
import time
from unittest import mock


import pytest
from autotrainer.core.animal.animal_subject import AnimalPelletCounts
from autotrainer.training import TrainingPlan, PlanInfo, LoadProgressResult

from autotrainer.behavior import TrainingMode
from autotrainer.behavior.behavior_algorithm import BehaviorAlgoStatus
from autotrainer.core import AnimalSubject
from autotrainer.device import EmulationInterface, Target
from autotrainer.device.device_interface import Acknowledge
from tools.acquisition.model.app_model import app_status_to_api_app_mode, app_status_to_behavior_algo_status, AppModel
from tools.acquisition.model.app_model_status import AppModelStatus

from autotrainer.api import ApiApplicationMode, ApiSystemStatus

from tools.acquisition.model.behavior_model import EmergencyControlSource


BEHAVIOR_SETTING_SOURCES = [
    ("is_pellet_delivery_enabled",
     lambda app, value: setattr(app.behavior.algorithm, "pellet_delivery_enabled", value)),
    ("is_pellet_cover_enabled",
     lambda app, value: setattr(app.behavior.algorithm, "pellet_cover_enabled", value)),
    ("is_intertrial_pellet_shift_enabled",
     lambda app, value: setattr(app.behavior.algorithm, "intertrial_pellet_shift_enabled", value)),
    ("is_triangle_pellet_distance_detection_enabled",
     lambda app, value: setattr(app.behavior.algorithm, "use_triangle_pellet_distance_too_far", value)),
    ("is_auto_close_gate_on_intertrial_enabled",
     lambda app, value: setattr(app.behavior.algorithm.auto_close_gate_on_intertrial_config, "enabled", value)),
    ("is_auto_clamp_enabled",
     lambda app, value: setattr(app.behavior.algorithm, "head_fixation_enabled", value)),
    ("is_batch_trials_enabled",
     lambda app, value: setattr(app.behavior.algorithm.batch_trial_recording_config, "enabled", value)),
]

PELLET_SETTING_SOURCES = [
    ("is_home_on_excessive_drift_enabled",
     lambda app, value: setattr(app.behavior.algorithm.home_on_excessive_drift_distance_config, "enabled", value)),
    ("is_tunnel_sweep_enabled",
     lambda app, value: setattr(app.analysis.auto_tunnel_sweep_monitor.config, "enabled", value)),
]


def _setting_ids(sources):
    return [entry[0] for entry in sources]



class TestStatus:

    @pytest.mark.parametrize("app_model_status", list(AppModelStatus))
    def test_it_can_translate_to_api_app_mode(self, app_model_status: AppModelStatus) -> None:
        api_app_mode = app_status_to_api_app_mode(app_model_status)
        assert isinstance(api_app_mode, ApiApplicationMode)

    @pytest.mark.parametrize("app_model_status", list(AppModelStatus))
    def test_it_can_translate_to_behavior_status(self, app_model_status: AppModelStatus):
        algo_status = app_status_to_behavior_algo_status(app_model_status)
        if app_model_status in {AppModelStatus.CALIBRATION_3D, AppModelStatus.CALIBRATION_DCS}:
            assert algo_status is None
        else:
            assert isinstance(algo_status, BehaviorAlgoStatus)
            assert algo_status.name == app_model_status.name



class TestSystemStatusPayload:

    def test_it_builds_a_system_status_payload(self, app_model):
        status = app_model._make_api_system_status_payload()
        assert isinstance(status, ApiSystemStatus)

    @pytest.mark.parametrize("is_open", [True, False])
    def test_it_reports_the_tunnel_gate_state(self, app_model, is_open):
        # read-only property; its only public write path is an inbound CAN property-change message.
        app_model.hardware._tunnel_gate_open_status = is_open
        status = app_model._make_api_system_status_payload()
        assert status.tunnel_device.is_gate_open is is_open

    @pytest.mark.parametrize("field_name,set_source", BEHAVIOR_SETTING_SOURCES,
                             ids=_setting_ids(BEHAVIOR_SETTING_SOURCES))
    @pytest.mark.parametrize("value", [True, False])
    def test_it_reports_each_behavior_setting(self, app_model, field_name, set_source, value):
        set_source(app_model, value)
        status = app_model._make_api_system_status_payload()
        assert getattr(status.behavior, field_name) is value

    @pytest.mark.parametrize("value", [True, False])
    def test_it_reports_live_analysis_enabled(self, app_model, monkeypatch, value):
        # is_enabled is a read-only property on InferenceProtocol; a plain bool on the class shadows it.
        monkeypatch.setattr(type(app_model.inference), "is_enabled", value)
        status = app_model._make_api_system_status_payload()
        assert status.behavior.is_live_analysis_enabled is value

    @pytest.mark.parametrize("field_name,set_source", PELLET_SETTING_SOURCES,
                             ids=_setting_ids(PELLET_SETTING_SOURCES))
    @pytest.mark.parametrize("value", [True, False])
    def test_it_reports_each_pellet_device_setting(self, app_model, field_name, set_source, value):
        set_source(app_model, value)
        status = app_model._make_api_system_status_payload()
        assert getattr(status.pellet_device, field_name) is value


def test_it_drain_record_stop_sema_on_session_recording_start(app_model):
    app_model._record_stop_sema.release()
    app_model._record_stop_sema.release()
    app_model.behavior.algorithm.start_trial_capture(reason="manual")
    assert app_model._record_stop_sema.acquire(block=False) is False, "cannot acquire after: it should be back to 0"


def test_resume_fails_if_hard_reconnect_fails(
    app_model,
    monkeypatch,
    mock_get_perf_now,
    caplog,
):
    app_model.capture_start(target_status=AppModelStatus.ACQUIRING)
    algo = app_model.behavior.algorithm
    hard = app_model.hardware
    analysis = app_model.analysis
    can_dev = hard.can_device
    dev_conn = hard.device_connection
    iface = can_dev.device_interface
    assert isinstance(iface, EmulationInterface)
    emergency_mon = analysis.emergency_alarm_monitor
    # analysis
    # put some randomness:
    uuid_nack_errno = random.getrandbits(32)
    if uuid_nack_errno == 0:
        uuid_nack_errno = -42
    def bad_delay(delay_sec):
        iface._messages.append(Acknowledge(uuid=iface.next_uuid(), error=uuid_nack_errno))
        return True
    monkeypatch.setattr(iface, iface.delay.__name__, bad_delay)
    with pytest.raises(RuntimeError, match=rf"uuid_nacks=\[{uuid_nack_errno}\]"):
        tokens = set()
        with dev_conn.await_acknowledge(tokens):
            tokens.add(hard.delay(1))
    p_end = time.perf_counter() + 0.5
    while time.perf_counter() < p_end:
        time.sleep(0.001)  # give some time processing for background threads, notably emergency monitor
        if algo.algo_paused:
            break
    assert algo.algo_paused
    assert emergency_mon.is_engaged
    assert analysis.device_comm_alarm.is_engaged
    # now try resume, for that we need keep increase simulate perf now
    stop_increase = threading.Event()
    def increase_perf_now():
        # NB: give some time for background threads to process the probe from emergency_resume,
        # and/but
        while not stop_increase.is_set():
            mock_get_perf_now.increase_simulate_perf_now(0.1)
            time.sleep(0.05)
    th = threading.Thread(target=increase_perf_now, daemon=True)
    th.start()
    orig_connect = hard.connect
    fail_conn = mock.MagicMock(side_effect=RuntimeError("faked failed connect"))
    monkeypatch.setattr(hard, hard.connect.__name__, fail_conn)
    try:
        app_model.behavior.emergency_resume(source=EmergencyControlSource.USER_BUTTON)
    finally:
        stop_increase.set()
        th.join()
    assert fail_conn.call_count >= 1
    assert algo.algo_paused  # still
    assert emergency_mon.is_engaged
    assert "before_emergency_resumed failed, skipping emergency_resume" in caplog.text
    # now:
    hard.connect = orig_connect
    app_model.behavior.emergency_resume(source=EmergencyControlSource.USER_BUTTON)
    assert not algo.algo_paused  # not anymore
    assert not emergency_mon.is_engaged
    assert emergency_mon.engaged_reasons == []


def test_board_reset_engage_emergency(
    app_model,
    monkeypatch,
    caplog,
):
    analysis = app_model.analysis
    system_fault = analysis.system_fault_alarm
    reset_det = analysis.boards_hardware_reset_detector
    reset_det.config.allow_autoresume_on_cleared = False  # force here
    reset_det.update_config()
    reset_det_engaged_transitions = []
    def prop_changed(name, value, prev_value):
        if name == system_fault.DETECTOR_PROPERTY_CHANGED:
            det, name, value = value
            if value != prev_value and det == reset_det:
                reset_det_engaged_transitions.append(value)
    # ensure system-fault is emergency cond:
    system_fault.config.is_emergency_condition = True
    app_model.capture_start(target_status=AppModelStatus.ACQUIRING)
    system_fault.property_changed += prop_changed
    reset_det.update_uptime(Target.PELLET_DEVICE, 50, is_boot=True)
    assert not reset_det.is_engaged  # it's reset with an analysis stop/start because of emergency stop
    assert reset_det_engaged_transitions == [True, False]  # engaged, then disengaged
    assert analysis.emergency_alarm_monitor.is_engaged  # but emergency alarm is kept engaged
    assert analysis.system_fault_alarm.is_engaged   # given system fault is engaged via the board hardware reset
    assert app_model.behavior.algorithm.algo_paused
    app_model.behavior.emergency_resume(EmergencyControlSource.USER_BUTTON)
    assert not analysis.emergency_alarm_monitor.is_engaged
    assert not reset_det.is_engaged
    assert not app_model.behavior.algorithm.algo_paused


class TestSelectedModeAnimalPlan:

    def make_plan(self):
        plan = TrainingPlan()
        self._plans_by_id[plan.plan_id] = plan
        return plan

    @pytest.fixture(autouse=True)
    def _pre_init(self, app_model, monkeypatch):
        self._plans_by_id = {}
        monkeypatch.setattr(
            app_model._plan_repo,
            app_model._plan_repo.get_plan.__name__,
            self._plans_by_id.get,
        )
        assert app_model.set_training_mode(TrainingMode.MANUAL_WITH_PROTOCOL) is True
            # need != MANUAL for attach/resume of training plan

    @pytest.fixture
    def animal1(self):
        animal1 = AnimalSubject(name="Animal1")
        idx_cnt = random.randint(1, 1000)
        for cnt in animal1.pellet_counts_day, animal1.pellet_counts_total:
            for field in dataclasses.fields(cnt):
                setattr(cnt, field.name, idx_cnt)
                idx_cnt += 1
        return animal1

    @pytest.fixture
    def plan1_advance(self, plan1, monkeypatch):
        ok = mock.MagicMock(return_value=True)
        monkeypatch.setattr(plan1, plan1._advance.__name__, ok)
        return ok

    @pytest.fixture
    def plan1_fallback(self, plan1, monkeypatch):
        ok = mock.MagicMock(return_value=True)
        monkeypatch.setattr(plan1, plan1._fallback.__name__, ok)
        return ok

    @pytest.fixture
    def plan1(self, animal1, monkeypatch):
        plan1 = self.make_plan()
        animal1.training.current_protocol = plan1.plan_id
        return plan1

    @pytest.fixture
    def plan1_resume_ok(self, plan1, monkeypatch):
        plan1_resume = mock.MagicMock(side_effect=lambda: True)
        monkeypatch.setattr(plan1, plan1.resume.__name__, plan1_resume)
        return plan1_resume

    @pytest.mark.parametrize("select", [True, False])
    def test_add_animal(self, app_model, select):
        callback = mock.MagicMock()
        animal = app_model.add_animal("new animal", select=select, callback=callback)
        assert isinstance(animal, AnimalSubject)
        assert app_model.selected_animal is (animal if select else None)
        assert app_model.get_animal_by_id(animal.id) is animal

    @pytest.mark.parametrize("select", [True, False])
    def test_add_empty_animal(self, app_model, animal1, select):
        app_model.set_selected_animal(animal1)
        assert app_model.selected_animal is animal1
        assert app_model.add_animal("", select=select) is None
        assert app_model.selected_animal is (None if select else animal1)

    def test_set_training_plans(self, app_model, caplog, animal1, plan1, plan1_resume_ok):
        assert app_model.set_selected_animal(animal1) is True
        assert plan1_resume_ok.call_args_list == [mock.call()]
        pli = PlanInfo(
            plan_id=plan1.plan_id,
            name=plan1.name,
            description=plan1.description,
        )
        app_model.set_training_plans([pli])
        assert f"reattaching plan {plan1.plan_id} to " in caplog.text
        assert plan1_resume_ok.call_args_list == [mock.call(), mock.call()]

    def test_selected_animal_mode_plan_basis(self, app_model, monkeypatch, animal1, plan1, plan1_resume_ok):
        assert app_model.selected_animal is None
        assert app_model.training_plan is None
        assert app_model.attached_plan is None
        callback = mock.MagicMock()
        assert app_model.set_selected_animal(animal1, callback=callback) is True
        assert app_model.selected_animal == animal1
        assert app_model.training_plan is plan1
        assert app_model.attached_plan is plan1
        assert callback.call_args_list == [mock.call(True)]
        assert plan1_resume_ok.call_args_list == [mock.call()]
        assert app_model.set_selected_animal(None) is True
        assert app_model.selected_animal is None
        assert app_model.training_plan is None
        assert app_model.attached_plan is None
        assert app_model.set_selected_animal(animal1) is True
        assert app_model.selected_animal is animal1
        assert app_model.training_plan is plan1
        assert app_model.attached_plan is plan1
        assert app_model.set_training_mode(TrainingMode.MANUAL) is True
        assert app_model.training_plan is plan1
        assert app_model.attached_plan is None
        assert app_model.set_training_mode(TrainingMode.AUTOMATIC) is True
        assert app_model.attached_plan is plan1
        assert app_model.set_training_mode(TrainingMode.MANUAL_WITH_PROTOCOL) is True
        assert app_model.attached_plan is plan1
        assert app_model.set_training_mode(TrainingMode.MANUAL) is True
        assert app_model.attached_plan is None
        plan2 = self.make_plan()
        plan2_resume = mock.MagicMock(side_effect=lambda: True)
        monkeypatch.setattr(plan2, plan2.resume.__name__, plan2_resume)
        assert app_model.set_training_plan(plan2)
        assert app_model.training_plan is plan2
        assert app_model.attached_plan is None
        assert app_model.set_training_mode(TrainingMode.AUTOMATIC) is True
        assert app_model.attached_plan is plan2

    @pytest.mark.parametrize("failed_resume", (mock.MagicMock(side_effect=RuntimeError("foobar")), mock.MagicMock(return_value=False)))
    def test_selected_animal_fails_restore_previous(self, app_model, monkeypatch, caplog, animal1, plan1, plan1_resume_ok, failed_resume):
        algo = app_model.behavior.algorithm
        animal2 = AnimalSubject()
        cnt_idx = random.randint(1, 100)
        for animal in (animal1, animal2):
            for cnt in (animal.pellet_counts_day, animal.pellet_counts_total):
                for field in dataclasses.fields(cnt):
                    cnt_idx += 1
                    setattr(cnt, field.name, cnt_idx)
        assert animal1.pellet_counts_day != animal2.pellet_counts_day
        assert animal1.pellet_counts_total != animal2.pellet_counts_total
        plan2 = self.make_plan()
        animal2.training.current_protocol = plan2.plan_id
        callback = mock.MagicMock()
        assert app_model.set_selected_animal(animal1, callback=callback) is True
        assert app_model.selected_animal == animal1
        assert app_model.training_plan == plan1
        assert callback.call_args_list == [mock.call(True)]
        assert plan1_resume_ok.call_args_list == [mock.call()]
        assert algo.pellet_consumed_day == animal1.pellet_counts_day.consumed
        assert algo.pellet_consumed_total == animal1.pellet_counts_total.consumed
        #
        monkeypatch.setattr(plan2, plan2.resume.__name__, failed_resume)
        callback = mock.MagicMock()
        assert app_model.set_selected_animal(animal2, callback=callback) is False
        assert failed_resume.call_args_list == [mock.call()]
        assert callback.call_args_list == [
            mock.call(False, error='set_training_plan returned false', load_result=None)]
        assert app_model.selected_animal == animal1
        assert app_model.training_plan == plan1
        # NB: also with _set_selected error:
        monkeypatch.setattr(
            app_model, app_model._set_selected_animal.__name__,
            mock.MagicMock(side_effect=RuntimeError("baz"))
        )
        with pytest.raises(RuntimeError, match="baz"):
            app_model.set_selected_animal(animal2)
        assert app_model.selected_animal == animal1
        assert app_model.training_plan == plan1
        assert algo.pellet_consumed_day == animal1.pellet_counts_day.consumed
        assert algo.pellet_consumed_total == animal1.pellet_counts_total.consumed

    def test_set_animal_error(self, app_model, monkeypatch, animal1, plan1):
        callback = mock.MagicMock()
        failed = mock.MagicMock(side_effect=RuntimeError("foobar"))
        monkeypatch.setattr(app_model, app_model._set_selected_animal.__name__, failed)
        #
        with pytest.raises(RuntimeError, match="foobar"):
            app_model.set_selected_animal(animal1)
        #
        assert app_model.set_selected_animal(animal1, callback=callback) is False
        assert callback.call_args_list == [mock.call(False, error='set_selected_animal error: foobar')]

    def test_set_animal_with_plan_error(self, app_model, monkeypatch, animal1, plan1):
        callback = mock.MagicMock()
        m_set_training_plan = mock.MagicMock(side_effect=RuntimeError("foobar"))
        monkeypatch.setattr(app_model, app_model._set_training_plan.__name__, m_set_training_plan)
        assert app_model.set_selected_animal(animal1, callback=callback) is False
        assert callback.call_args_list == [
            mock.call(False, error="set_training_plan error: foobar", load_result=None)]
        assert app_model.selected_animal is None
        #
        def set_training_plan_load_out_of_date(*args, callback=None, **kwargs):
            callback(False, error="foobar", load_result=LoadProgressResult.OUT_OF_DATE)
            return False
        m_set_training_plan.reset_mock()
        m_set_training_plan.side_effect = set_training_plan_load_out_of_date
        callback.reset_mock()
        assert app_model.set_selected_animal(animal1, callback=callback) is False
        assert callback.call_args_list == [mock.call(False, error=mock.ANY, load_result=LoadProgressResult.OUT_OF_DATE)]

    def test_unselect_animal_detach_plan(self, app_model, animal1, plan1, plan1_resume_ok):
        algo = app_model.behavior.algorithm
        assert app_model.attached_plan is None
        assert app_model.training_plan is None
        assert algo.pellet_consumed_total == 0
        assert algo.pellet_consumed_day == 0
        assert app_model.set_selected_animal(animal1) is True
        assert app_model.attached_plan is plan1
        assert app_model.training_plan is plan1
        assert algo.pellet_consumed_total > 0
        assert algo.pellet_consumed_day > 0
        assert app_model.set_selected_animal(None) is True
        assert app_model.attached_plan is None
        assert app_model.training_plan is None
        assert algo.pellet_consumed_total == 0
        assert algo.pellet_consumed_day == 0

    def test_set_training_plan_fails_restore_previous(self, app_model, monkeypatch, caplog, animal1, plan1, plan1_resume_ok):
        plan2 = self.make_plan()
        animal1.training.current_protocol = plan1.plan_id
        assert app_model.set_selected_animal(animal1) is True
        assert app_model.selected_animal == animal1
        assert app_model.training_plan == plan1
        failed_resume = mock.MagicMock(side_effect=RuntimeError("foobar"))
        monkeypatch.setattr(plan2, plan2.resume.__name__, failed_resume)
        callback = mock.MagicMock()
        assert app_model.set_training_plan(plan2, callback=callback) is False
        assert failed_resume.call_args_list == [mock.call()]
        assert app_model.training_plan == plan1
        assert app_model.attached_plan == plan1
        assert callback.call_args_list == [mock.call(False, error=mock.ANY)]
        assert "foobar" in caplog.text

    def test_set_training_plan_error(self, app_model, animal1, plan1, monkeypatch):
        failed = mock.MagicMock(side_effect=RuntimeError("foobar"))
        monkeypatch.setattr(app_model, app_model._set_training_plan.__name__, failed)
        with pytest.raises(RuntimeError, match="foobar"):
            app_model.set_training_plan(plan1)
        #
        callback = mock.MagicMock()
        assert app_model.set_training_plan(plan1, callback=callback) is False
        assert callback.call_args_list == [mock.call(False, 'set_training_plan error: foobar')]

    def test_set_selected_animal_already_selected(self, app_model, animal1):
        assert app_model.set_selected_animal(animal1) is True
        callback = mock.MagicMock()
        assert app_model.set_selected_animal(animal1, callback=callback) is True
        assert app_model.selected_animal == animal1
        assert callback.call_args_list == [mock.call(True)]

    def test_set_plan_already_set(self, app_model, animal1, plan1, plan1_resume_ok):
        assert app_model.set_selected_animal(animal1) is True
        assert app_model.training_plan == plan1
        callback = mock.MagicMock()
        assert app_model.set_training_plan(plan1, callback=callback) is True
        assert app_model.selected_animal == animal1
        assert callback.call_args_list == [mock.call(True)]

    def test_set_training_mode_basis(self, app_model, monkeypatch):
        assert app_model.training_mode == TrainingMode.MANUAL_WITH_PROTOCOL
        callback = mock.MagicMock()
        assert app_model.set_training_mode(TrainingMode.MANUAL, callback=callback) is True
        assert callback.call_args_list == [mock.call(True)]
        assert app_model.training_mode == TrainingMode.MANUAL
        callback = mock.MagicMock()
        assert app_model.set_training_mode(TrainingMode.MANUAL, callback=callback) is True
        assert callback.call_args_list == [mock.call(True)]

    def test_set_training_mode_error(self, app_model, monkeypatch):
        exc = RuntimeError("foobar")
        failed = mock.MagicMock(side_effect=exc)
        monkeypatch.setattr(app_model, app_model._set_training_mode.__name__, failed)
        #
        with pytest.raises(RuntimeError, match="foobar"):
            app_model.set_training_mode(TrainingMode.AUTOMATIC)
        #
        callback = mock.MagicMock()
        assert app_model.set_training_mode(TrainingMode.AUTOMATIC, callback=callback) is False
        assert callback.call_args_list == [mock.call(False, error='set_training_mode error: foobar')]

    def test_set_something_while_another_in_progress(self, app_model, request, monkeypatch, animal1, plan1):
        slow_evt = threading.Event()
        request.addfinalizer(slow_evt.set)
        def slow_resume():
            slow_evt.wait(10)
        monkeypatch.setattr(plan1, plan1.resume.__name__, slow_resume)
        app_model.set_selected_animal(animal1, background=True)
        # without cb:
        with pytest.raises(RuntimeError, match="Refusing to submit change of selected_animal"):
            app_model.set_selected_animal(animal1, background=True)
        # with cb:
        cb_res_err = None
        def cb(result, *, error=None):
            nonlocal cb_res_err
            cb_res_err = (result, error)
        assert app_model.set_selected_animal(animal1, background=True, callback=cb) is False
        assert cb_res_err == (
            False,
            "Refusing to submit change of selected_animal when another change already in progress (or submitted)"
        )

    def test_get_error_if_queue_full(self, app_model, request, monkeypatch, animal1):
        filled_evt = threading.Event()
        block_evt = threading.Event()
        request.addfinalizer(block_evt.set)
        animal2 = AnimalSubject()
        def cb(result, *, error=None):
            # this callback is called from the worker thread,
            # so let's use this to fill the queue, while the worker is here:
            for _ in range(app_model._worker_thread_queue.maxsize):
                app_model.set_selected_animal(animal2, background=True)
            app_model._worker_submit_in_progress = False  # fake
            filled_evt.set()
            block_evt.wait()
        app_model.set_selected_animal(animal1, background=True, callback=cb)
        assert filled_evt.wait(5)  # should very quick
        with pytest.raises(RuntimeError, match="worker thread queue is full"):
            app_model.set_selected_animal(animal2, background=True, callback=cb)

    @pytest.mark.parametrize("func", (AppModel.plan_advance_phase.__name__, AppModel.plan_fallback_phase.__name__))
    def test_change_phase(self, app_model, animal1, plan1, plan1_resume_ok,
                           plan1_advance, plan1_fallback, func):
        assert app_model.set_selected_animal(animal1) is True
        #
        method = getattr(app_model, func)
        assert method(plan1) is True
        done = threading.Event()
        cb_res = None
        def cb(result, *, error=None):
            nonlocal cb_res
            cb_res = (result, error)
            done.set()
        assert method(plan1, callback=cb, background=True) is None
        assert done.wait(5)
        assert cb_res == (True, None)
