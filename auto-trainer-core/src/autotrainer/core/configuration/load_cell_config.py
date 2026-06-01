from dataclasses import dataclass
from typing import Dict, Any
from typing_extensions import Self

from autotrainer.core import build_kwargs_apply_mapping
from autotrainer.core.configuration.detector import DetectorConfig


@dataclass
class LoadCellConfiguration(DetectorConfig):

    # NB: this is the current/previous value used on agx001:
    weight_active_threshold: float = 2  # grams ; if above then will become engaged if above for threshold_duration
    weight_inactive_threshold: float = 2  # grams ;
    # if below then will become disengaged if below for more than

    threshold_duration: float = 0.25
    # duration threshold for engaged or thrashing_detected, must remain during that delay to make the change

    min_event_duration: float = 5.0
    min_post_event_hold_duration: float = 2.0
    # delay before inactive if was engaged/active for more than min_event_duration

    thrashing_var_weight_threshold_min: float = 20  # grams
    thrashing_var_weight_threshold_max: float = 30  # grams
    thrashing_var_min_delay: float = 0.05  # seconds
    thrashing_var_max_delay: float = 0.2  # seconds
    thrashing_min_ptp_change_count: int = 3  # nbr of "ptp" change needed in a row during var_max_delay

    # allow to filter out values smaller than min, or larger than max :
    weight_min_filter: float = -500  # grams
    weight_max_filter: float = 500  # grams

    @classmethod
    def from_version_zero(cls, content: Dict[str, Any]) -> Self:
        return cls(**build_kwargs_apply_mapping(content, (
            ('weight_active_threshold', 'load_trigger'),
            ('threshold_duration', 'min_load_on_duration'),
            ('min_post_event_hold_duration', 'min_load_off_duration'),
        )))

    @classmethod
    def from_version_one(cls, content: Dict[str, Any]) -> Self:
        return cls(**build_kwargs_apply_mapping(content, (
            ('weight_active_threshold', 'threshold'),
        )))


@dataclass
class LoadCellAutoTareConfiguration(DetectorConfig):
    threshold: float = 0.1
    range_threshold: float = 0.75
    duration: float = 2.0
    sample_rate: int = 100

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        kwargs = {}
        for k in {"threshold", "range_threshold", "duration", "sample_rate"}:
            val = content.get(k)
            if val is not None:
                kwargs[k] = val
        return cls(**kwargs)
