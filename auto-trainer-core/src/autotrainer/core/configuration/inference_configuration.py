from dataclasses import dataclass

from typing_extensions import Self

from autotrainer.core import build_kwargs_apply_mapping, make_camelize_representer, make_decamelize_constructor


@dataclass
class InferenceConfiguration:
    pose_model_location: str = ""
    is_enabled: bool = False
    intersession_wait_time: float = 2.0
    """
    The amount of time to wait for the video files to be available for processing.  This is more of a system property
    than an algorithm/behavior property.
    """

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(**build_kwargs_apply_mapping(content, (
            ('pose_model_location', 'model'),
        )))


inference_configuration_representer = make_camelize_representer("!InferenceConfiguration")
inference_configuration_constructor = make_decamelize_constructor(InferenceConfiguration)
