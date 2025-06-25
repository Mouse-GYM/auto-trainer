import numpy
import pytest

from autotrainer.core.analysis import LoadCellTareMonitor


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
