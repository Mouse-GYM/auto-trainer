import math
from dataclasses import dataclass

from typing_extensions import Self

from autotrainer.core import build_kwargs_apply_mapping


@dataclass
class _InferenceConfiguration:
    pose_model_location: str = ""
    is_enabled: bool = False
    min_confidence_plot_threshold: float = 0.9
    min_confidence_presence_threshold: float = 0.9

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        content.pop("intertrial_wait_time", None)  # was deprecated/removed
        return cls(**build_kwargs_apply_mapping(content, (
            ('pose_model_location', 'model'),
        )))


@dataclass
class InferenceConfiguration(_InferenceConfiguration):

    def __init__(self, **kwargs):
        kwargs.pop("intersession_wait_time", None)  # was deprecated/removed
        super().__init__(**kwargs)

    def __post_init__(self):
        for name, thresh_val in (
            ('min_confidence_plot_threshold', self.min_confidence_plot_threshold),
            ('min_confidence_presence_threshold', self.min_confidence_presence_threshold),
        ):
            if not math.isfinite(thresh_val) or not 0 <= thresh_val <= 1:
                raise ValueError(f"Invalid value for {name}: {thresh_val}")
