from autotrainer.video.detection import PresenceDetectionAttrs


def test_properties():
    attrs = PresenceDetectionAttrs()
    assert attrs.presence_detected is False
    attrs.presence_detected = True
    assert attrs.presence_detected is True
    #
    assert attrs.movement_detected is False
    attrs.movement_detected = True
    assert attrs.movement_detected is True
    #
    assert attrs.pc_sum == 0
    attrs.pc_sum = 42
    assert attrs.pc_sum == 42
