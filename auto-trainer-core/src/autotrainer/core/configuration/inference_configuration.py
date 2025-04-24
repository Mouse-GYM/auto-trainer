from dataclasses import dataclass

import humps
import yaml

from typing_extensions import Self


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
        return cls(
            pose_model_location=content.get("model", ""),
            is_enabled=content.get("is_enabled", False),
            intersession_wait_time=content.get("intersession_wait_time", 2.0)
        )


def inference_configuration_representer(dumper: yaml.SafeDumper, c: InferenceConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!InferenceConfiguration", {
        "poseModelLocation": c.pose_model_location,
        "isEnabled": c.is_enabled,
        "intersessionWaitTime": c.intersession_wait_time
    })


def inference_configuration_constructor(loader: yaml.SafeLoader,
                                        node: yaml.nodes.MappingNode) -> InferenceConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return InferenceConfiguration(**humps.decamelize(content))
