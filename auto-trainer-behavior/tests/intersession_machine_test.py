import datetime
from unittest import mock

import pytest
from autotrainer.core import ProjectInfo
from transitions import MachineError

from autotrainer.behavior import SegmentationConfiguration, DetectionConfiguration, SystemState
from autotrainer.behavior.intersession import IntersessionState
from top_fixtures import MockSystemMachine


def test_intersession(
    mock_system,
    machine,
):
    intersession = machine.intersession

    assert intersession.project is not None
    assert intersession.state == IntersessionState.idle

    with pytest.raises(MachineError):
        seg_cfg = SegmentationConfiguration(
            nonce="foobar",
            session_index=42,
            session_when=datetime.datetime.now(),
            complete=lambda n, s: 1 / 0,  # noqa
        )
        intersession.perform_detection(seg_cfg)

    machine.state = SystemState.intersession

    with mock_system.mock_perform_segmentation() as m_perf_segm:
        intersession.perform_segmentation()

    segment_cfg = intersession._segmentation_configuration

    assert m_perf_segm.call_args_list == [
        mock.call(segment_cfg)
    ]

    assert intersession.state == IntersessionState.segmentation

    with mock_system.mock_perform_detection() as m_perf_detect:
        segment_cfg.complete(segment_cfg.nonce, True)

    assert intersession.state == IntersessionState.detection

    detection_cfg = intersession._detection_configuration
    assert m_perf_detect.call_args_list == [
        mock.call(detection_cfg)
    ]

    assert intersession.state == IntersessionState.detection

    detection_cfg.complete(detection_cfg.nonce, True)

    assert intersession.state == IntersessionState.idle

    assert mock_system.intersession_state_trans == [
        IntersessionState.segmentation,
        IntersessionState.detection,
        IntersessionState.idle,
    ]
