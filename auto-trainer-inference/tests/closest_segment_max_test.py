import numpy as np

from autotrainer.inference.analysis.parse_pellet_presentations_jetson import _closest_segment_max


def make_segment(max_frame: int) -> dict:
    return {"init": max_frame - 10, "end": max_frame + 10, "max": max_frame}


def make_distances(distance_by_frame: dict) -> np.ndarray:
    """Stand-in for dist_hvpp_R: hand-to-pellet distance per frame, far away except where stated."""
    distances = np.full(200, 99.0)
    for frame, distance in distance_by_frame.items():
        distances[frame] = distance
    return distances


def test_no_segments_gives_none():
    assert _closest_segment_max([], make_distances({})) is None


def test_single_segment_gives_its_max():
    assert _closest_segment_max([make_segment(40)], make_distances({40: 3.5})) == 40


def test_picks_the_closest_segment_not_the_first_or_last():
    # the closest is the middle one, so neither a first-wins nor a last-wins bug can pass this
    distances = make_distances({20: 9.0, 50: 2.0, 80: 7.0})
    segments = [make_segment(20), make_segment(50), make_segment(80)]
    assert _closest_segment_max(segments, distances) == 50


def test_slice_keeps_an_earlier_presentation_out_of_the_selection():
    # the earlier presentation's segments sit closer to the pellet; slicing reach_events from the
    # watermark must stop them being selected for the later presentation
    distances = make_distances({10: 0.5, 15: 0.8, 60: 6.0, 70: 4.0})
    reach_events = [make_segment(10), make_segment(15), make_segment(60), make_segment(70)]
    reach_events_start = 2
    assert _closest_segment_max(reach_events[reach_events_start:], distances) == 70
