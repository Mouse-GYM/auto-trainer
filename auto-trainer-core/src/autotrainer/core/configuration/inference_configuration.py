from dataclasses import dataclass

from typing_extensions import Self

from autotrainer.core import build_kwargs_apply_mapping, make_camelize_representer, make_decamelize_constructor


@dataclass
class _InferenceConfiguration:
    pose_model_location: str = ""
    is_enabled: bool = False

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
