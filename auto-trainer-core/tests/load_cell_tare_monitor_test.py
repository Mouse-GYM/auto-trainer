import math

import numpy
import pytest

from autotrainer.core.analysis.load_cell_tare_monitor import LoadCellTareMonitor


@pytest.mark.parametrize("threshold, range_threshold", [
    (0.1, 1),
    (0.5, 2),
    (1, 1.5),
])
@pytest.mark.parametrize("sample_rate", [20, 250])
@pytest.mark.parametrize("duration", [0.5, 1.5])
def test_baseline_depends_on_cb_return(threshold, range_threshold, sample_rate, duration):
    monitor = LoadCellTareMonitor()
    monitor.threshold = threshold
    monitor.range_threshold = range_threshold
    monitor.sample_rate = sample_rate
    monitor.duration = duration
    #
    assert monitor.baseline == 0
    #
    # could use some variability in values too (but below range_threshold):
    values = numpy.asarray([monitor.threshold + 0.01] * int(monitor.sample_rate * monitor.duration))
    #
    monitor.tare_callback = lambda: False
    monitor.update(list(values))
    assert monitor.baseline == numpy.average(values)
    #
    monitor.tare_callback = lambda: True
    values *= 2
    values += 0.00001
    monitor.update(list(values))
    assert monitor.baseline == 0


def test_low_variance_with_nans():
    monitor = LoadCellTareMonitor()
    values = numpy.asarray([monitor.threshold + 0.01] * int(monitor.sample_rate * monitor.duration))
    values[0] = 1.5 * monitor.range_threshold
    values[1] = math.nan
    values[-3] = math.nan
    values[-1] = monitor.range_threshold + 5
    monitor.update(list(values))
    assert not monitor.context.low_variance_engaged


def test_with_non_matching_update_values_len():
    monitor = LoadCellTareMonitor()
    values = list(range(9))
    monitor._index = len(monitor._values) - 4
    monitor.update(values)
    assert (monitor._values[-4:] == [0, 1, 2, 3]).all()
    assert (monitor._values[:5] == [4, 5, 6, 7, 8]).all()


def test_with_more_values_than_buffer_size():
    monitor = LoadCellTareMonitor()
    values = list(range(250))  # reminder: default buffer size is 200
    monitor.update(values)
    assert (monitor._values == list(range(50, 250))).all()
    assert monitor._index == 0
