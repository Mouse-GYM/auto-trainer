import pytest

from autotrainer.behavior.behavior_algorithm import BehaviorAlgoStatus
from tools.acquisition.model.app_model import AppModelStatus

from autotrainer.api.command.status_response import ApiAppStatus


class TestStatus:

    @pytest.mark.parametrize("app_model_status", list(AppModelStatus))
    def test_it_can_translate_to_api_app_status(self, app_model_status: AppModelStatus) -> None:
        api_app_status = app_model_status.to_api_app_status()
        assert isinstance(api_app_status, ApiAppStatus)

    @pytest.mark.parametrize("app_model_status", list(AppModelStatus))
    def test_it_can_translate_to_behavior_status(self, app_model_status: AppModelStatus):
        algo_status = app_model_status.to_behavior_algo_status()
        if app_model_status in {AppModelStatus.CALIBRATION_3D, AppModelStatus.CALIBRATION_DCS}:
            assert algo_status is None
        else:
            assert isinstance(algo_status, BehaviorAlgoStatus)
            assert algo_status.name == app_model_status.name
