import threading
from unittest import mock

import pytest

import time

from autotrainer.api import ApiAlarmKind, ApiEventKind

from autotrainer.core import LoadCellMonitor, get_perf_now
from autotrainer.core.analysis.animal_thrash_alarm import AnimalThrashAlarm
from autotrainer.core.analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitor
from top_fixtures import AlmostEqualFloat, has_api_event_kind


@pytest.fixture(autouse=True)
def _use_mock_event_mgr(mock_event_manager):
    pass


class AnimalThrash(AnimalThrashAlarm):

    def __init__(
        self,
        *args, **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.event_check_done = threading.Event()

    def _check_state(self):
        super()._check_state()
        self.event_check_done.set()
        # force very small next delay on purpose:
        return 0.000_000_001  # relying on mocked get_perf_now.


@pytest.fixture()
def load_cell():
    det = LoadCellMonitor()
    det.start()
    try:
        yield det
    finally:
        det.stop()


@pytest.fixture()
def audio_det():
    det = AudioSpectrumThrashMonitor()
    det.start()
    try:
        yield det
    finally:
        det.stop()


@pytest.fixture()
def mon(load_cell, audio_det):
    mon = AnimalThrash(load_cell_detector=load_cell, audio_thrash_detector=audio_det)
    try:
        yield mon
    finally:
        mon.stop()


@pytest.mark.parametrize("aggr_delay", [3, 5, 9, 15])
def test_it_engages_disengages_with_aggr_delay(
    mon,
    load_cell,
    audio_det,
    mock_get_perf_now,
    mock_event_manager,
    aggr_delay,
):
    mon.config.aggregate_delay = aggr_delay
    mon.config.audio_thrash_percent_on = 50
    mon.config.load_cell_thrash_percent_on = 50
    mon.start()
    start_p = get_perf_now()  # ~0
    load_cell.is_engaged = True
    load_cell.thrashing_detected = True
    audio_det.is_engaged = True
    mock_get_perf_now.increase_simulate_perf_now(aggr_delay / 4)
    mon.event_check_done.clear()
    assert mon.event_check_done.wait(5)
    assert not mon.is_engaged
    mock_get_perf_now.increase_simulate_perf_now(aggr_delay / 4 + 0.05)
    mon.event_check_done.clear()
    assert mon.event_check_done.wait(5)
    tot_dur = get_perf_now() - start_p
    assert mon.is_engaged
    assert tot_dur == AlmostEqualFloat(aggr_delay / 2), "duration before animal thrash engage"
    # NB: tot_dur ~= aggr_delay / 2, given using default 50%
    time.sleep(0.001)  # give small extra time to daemon thread: it sets is_engaged before sending the API event,
    assert has_api_event_kind(ApiEventKind.alarmChanged)
    mock_event_manager.reset_mock()
    assert not has_api_event_kind(ApiEventKind.alarmChanged)
    # now disable load-cell thrash:
    load_cell.thrashing_detected = False
    while mon.is_engaged:
        assert not has_api_event_kind(ApiEventKind.alarmChanged)
        mock_get_perf_now.increase_simulate_perf_now(1)
        mon.event_check_done.clear()
        assert mon.event_check_done.wait(5)
    assert not mon.is_engaged
    time.sleep(0.001)  # give small extra time to daemon thread: it sets is_engaged before sending the API event,
    # so this must be quite enough for it (see above next_delay forced to very small) to do that here.
    assert has_api_event_kind(ApiEventKind.alarmChanged)
    engaged_dur = mon.engaged_age
    assert abs(engaged_dur - aggr_delay / 2) < 2
