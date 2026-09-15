import pytest

from autotrainer.behavior.behavior_algorithm import BehaviorAlgoStatus
from tools.acquisition.model.app_model import app_status_to_api_app_mode, app_status_to_behavior_algo_status
from tools.acquisition.model.app_model_status import AppModelStatus

from autotrainer.api import ApiApplicationMode
from autotrainer.api.api_system_status import ApiSystemStatus


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
