""" Test handling of head fix device measurement data

Test the individual parse measurements and measurements functions.  Also test the integration of these functions
in the head fix device.
"""
import pytest

from autotrainer.device import parse_measurement, parse_measurements, HeadFix


def _assert_incomplete(data: str) -> None:
    measurement, residual = parse_measurement(data)
    assert measurement is None
    assert residual == data


def test_parse_valid_measurement():
    measurement, residual = parse_measurement("s32d0a18t238h557n")

    assert measurement is not None

    assert measurement.weight == pytest.approx(3.2, abs=1e-6, rel=1e-9)
    assert measurement.switch == 0
    assert measurement.pressure == 18
    assert measurement.temperature == pytest.approx(23.8, abs=1e-6, rel=1e-9)
    assert measurement.humidity == pytest.approx(55.7, abs=1e-6, rel=1e-9)

    assert residual == ""

    # Valid start, complete except for trailing close marker ('n')
    measurement, residual = parse_measurement("s32d0a18t238h557")
    assert measurement is not None
    assert residual == ""


def test_parse_incomplete_measurement():
    # Valid start, incomplete
    _assert_incomplete("s32d0a18")

    # Invalid start, valid close marker
    _assert_incomplete("32d0a18t238h557n")

    # Invalid
    _assert_incomplete("2d0a18t238h55")


def _assert_measurement_list(measurements: list, expected_count: int, residual: str, expected_residual: str) -> None:
    assert len(measurements) == expected_count
    assert residual == expected_residual


def test_multiple_measurements():
    measurements, residual = parse_measurements("s32d0a18t")
    _assert_measurement_list(measurements, 0, residual, "s32d0a18t")

    measurements, residual = parse_measurements("s32d0a18t238h557")
    _assert_measurement_list(measurements, 1, residual, "")

    measurements, residual = parse_measurements("s32d0a18t238h557n")
    _assert_measurement_list(measurements, 1, residual, "")

    measurements, residual = parse_measurements("s0d0a101t292h333ns-1d0a101t292h333n")
    _assert_measurement_list(measurements, 2, residual, "")

    measurements, residual = parse_measurements("s0d0a102t292h333ns0d0a101t292h333n")
    _assert_measurement_list(measurements, 2, residual, "")

    measurements, residual = parse_measurements("s32d0a18t238h557n\rs32d0a18t")
    _assert_measurement_list(measurements, 1, residual, "s32d0a18t")

    measurements, residual = parse_measurements("s32d0a18t238h557n\ns32d0a18t238h557n")
    _assert_measurement_list(measurements, 2, residual, "")

    measurements, residual = parse_measurements("s32d0a18t238h557n\ns32d0a18t238h557n\r\ns32d0a18t238h557n")
    _assert_measurement_list(measurements, 3, residual, "")


def test_device_measurements():
    device = HeadFix(None)

    assert device is not None

    assert len(device.measurements) == 0

    residual = device.insert_measurements("s32d0a18t238h557n\rs32d0a18t")
    _assert_measurement_list(device.measurements, 1, residual, "s32d0a18t")
