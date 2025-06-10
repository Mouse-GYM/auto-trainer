from unittest import mock

import pytest
from transitions import MachineError

from autotrainer.behavior import IntersessionState, SegmentationConfiguration, DetectionConfiguration


def test_intersession(
    mock_system, machine,
):
    intersession = machine.intersession

    assert intersession.state == IntersessionState.idle

    with pytest.raises(MachineError):
        intersession.perform_detection()

    with mock_system.mock_perform_segmentation() as m_perf_segm:
        intersession.perform_segmentation()

    assert m_perf_segm.call_args_list == [
        mock.call(SegmentationConfiguration(
            nonce=machine._intersession._segmentation_configuration.nonce,
            session_index=1,
            complete=machine._intersession._segmentation_complete,
        ))
    ]

    assert intersession.state == IntersessionState.segmentation

    segment_cfg = machine._intersession._segmentation_configuration
    with mock_system.mock_perform_detection() as m_perf_detect:
        segment_cfg.complete(segment_cfg.nonce, True)

    assert intersession.state == IntersessionState.detection
    detection_cfg = machine._intersession._detection_configuration
    assert m_perf_detect.call_args_list == [
        mock.call(DetectionConfiguration(
            nonce=detection_cfg.nonce,
            complete=machine._intersession._detection_complete,
        ))
    ]

    detection_cfg.complete(segment_cfg.nonce, True)

    assert intersession.state == IntersessionState.idle
    assert mock_system.intersession_state_trans == [
        IntersessionState.segmentation,
        IntersessionState.detection,
        IntersessionState.idle,
    ]
