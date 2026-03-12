from autotrainer.core.video_detection import PresenceDetectionAttrs


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


def test_to_local_value():
    attrs = PresenceDetectionAttrs()
    attrs.movement_detected = True
    attrs.pc_high_exclude_threshold += 15
    new_attrs = attrs.to_local_value()
    assert new_attrs == attrs
    assert new_attrs is not attrs
    assert new_attrs.presence_detected is False
    assert new_attrs.movement_detected is True
    # now:
    new_attrs.pc_sum += 5
    assert attrs != new_attrs
    with new_attrs.lock:
        pass
