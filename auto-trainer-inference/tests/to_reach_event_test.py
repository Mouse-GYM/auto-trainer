from typing import Optional

import pytest

from autotrainer.core.reach_event import ReachEventMethod, ReachEventOutcome
from autotrainer.inference.analysis.intertrial_process import (
    _to_hand_reach_events,
    _to_other_reach_events,
    _to_reach_event,
)


def make_pellet_event(*, placed: int = 300, lost: Optional[int] = 450,
                      method: str = ReachEventMethod.RIGHT_HAND,
                      outcome: str = ReachEventOutcome.EATEN) -> dict:
    return {"placed": placed, "lost": lost, "method": method, "outcome": outcome}


def test_maps_the_pellet_fields_onto_the_reach_event():
    event = _to_reach_event(make_pellet_event(), frame_rate=150, t_presented=1.0, max_frame=370)
    assert event.init == 300
    assert event.end == 450
    assert event.max == 370
    assert event.method == ReachEventMethod.RIGHT_HAND
    assert event.outcome == ReachEventOutcome.EATEN


def test_delay_is_the_placed_frame_relative_to_the_presented_time():
    event = _to_reach_event(make_pellet_event(placed=300), frame_rate=150, t_presented=1.5, max_frame=None)
    assert event.delay_since_presented == pytest.approx(300 / 150 - 1.5)


def test_carries_a_none_max_for_a_presentation_without_an_accepted_segment():
    event = _to_reach_event(make_pellet_event(), frame_rate=150, t_presented=0.0, max_frame=None)
    assert event.max is None


def test_carries_the_other_events_placeholder_max():
    event = _to_reach_event(make_pellet_event(), frame_rate=150, t_presented=0.0, max_frame=-1)
    assert event.max == -1


def test_keeps_a_none_end_when_the_pellet_was_never_lost():
    pellet_event = make_pellet_event(lost=None, method=ReachEventMethod.NONE,
                                     outcome=ReachEventOutcome.NONE)
    event = _to_reach_event(pellet_event, frame_rate=150, t_presented=0.0, max_frame=-1)
    assert event.end is None


def test_hand_events_take_the_stamped_max():
    pellet_event = make_pellet_event()
    pellet_event["max"] = 370
    events = _to_hand_reach_events([pellet_event], frame_rate=150, t_presented=0.0)
    assert [event.max for event in events] == [370]


def test_hand_events_without_a_stamped_max_are_unknown():
    # segmentation leaves the key absent for a left-hand presentation, and for any presentation whose
    # candidate reaches were all rejected
    events = _to_hand_reach_events([make_pellet_event(method=ReachEventMethod.LEFT_HAND)],
                                   frame_rate=150, t_presented=0.0)
    assert [event.max for event in events] == [None]


def test_other_events_take_the_placeholder_max_even_when_one_was_stamped():
    pellet_event = make_pellet_event(method=ReachEventMethod.TONGUE)
    pellet_event["max"] = 370
    events = _to_other_reach_events([pellet_event], frame_rate=150, t_presented=0.0)
    assert [event.max for event in events] == [-1]


def test_converting_an_empty_list_yields_no_events():
    assert _to_hand_reach_events([], frame_rate=150, t_presented=0.0) == []
    assert _to_other_reach_events([], frame_rate=150, t_presented=0.0) == []
