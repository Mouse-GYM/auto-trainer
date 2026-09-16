import numpy as np

from autotrainer.core.reach_event import ReachEventMethod, ReachEventOutcome
from autotrainer.inference.analysis.parse_pellet_presentations_jetson import _stamp_segment_max


def make_pellet_event(method: str) -> dict:
    return {"placed": 0, "lost": 200, "method": method, "outcome": ReachEventOutcome.EATEN}


def make_segment(max_frame: int) -> dict:
    return {"init": max_frame - 10, "end": max_frame + 10, "max": max_frame}


def make_distances(distance_by_frame: dict) -> np.ndarray:
    """Stand-in for dist_hvpp_R: hand-to-pellet distance per frame, far away except where stated."""
    distances = np.full(200, 99.0)
    for frame, distance in distance_by_frame.items():
        distances[frame] = distance
    return distances


def test_right_hand_presentation_is_stamped_with_the_closest_segment():
    pellet_event = make_pellet_event(ReachEventMethod.RIGHT_HAND)
    segments = [make_segment(20), make_segment(50), make_segment(80)]
    _stamp_segment_max(pellet_event, segments, make_distances({20: 9.0, 50: 2.0, 80: 7.0}))
    assert pellet_event["max"] == 50


def test_left_hand_presentation_is_never_stamped():
    # segmentation is right-hand only, so an accepted segment says nothing about this presentation
    pellet_event = make_pellet_event(ReachEventMethod.LEFT_HAND)
    _stamp_segment_max(pellet_event, [make_segment(50)], make_distances({50: 2.0}))
    assert "max" not in pellet_event


def test_tongue_presentation_is_never_stamped():
    pellet_event = make_pellet_event(ReachEventMethod.TONGUE)
    _stamp_segment_max(pellet_event, [make_segment(50)], make_distances({50: 2.0}))
    assert "max" not in pellet_event


def test_unclassified_presentation_is_never_stamped():
    pellet_event = make_pellet_event(ReachEventMethod.NONE)
    _stamp_segment_max(pellet_event, [make_segment(50)], make_distances({50: 2.0}))
    assert "max" not in pellet_event


def test_right_hand_presentation_without_accepted_segments_is_not_stamped():
    pellet_event = make_pellet_event(ReachEventMethod.RIGHT_HAND)
    _stamp_segment_max(pellet_event, [], make_distances({}))
    assert "max" not in pellet_event


def test_stamping_leaves_the_other_presentation_fields_alone():
    pellet_event = make_pellet_event(ReachEventMethod.RIGHT_HAND)
    _stamp_segment_max(pellet_event, [make_segment(50)], make_distances({50: 2.0}))
    assert pellet_event["placed"] == 0
    assert pellet_event["lost"] == 200
    assert pellet_event["method"] == ReachEventMethod.RIGHT_HAND
    assert pellet_event["outcome"] == ReachEventOutcome.EATEN
