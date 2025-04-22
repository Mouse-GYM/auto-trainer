from dataclasses import dataclass

import humps
from typing_extensions import Self

import yaml


@dataclass
class HardwareConfiguration:
    tunnel_identifier: str = ""
    pellet_identifier: str = ""

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        configuration = cls()

        if "head_fix" in content:
            configuration.tunnel_identifier = content["head_fix"].get("port", "")
        if "pellet_delivery" in content:
            configuration.pellet_identifier = content["pellet_delivery"].get("port", "")

        return configuration


def hardware_configuration_representer(dumper: yaml.SafeDumper, c: HardwareConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!HardwareConfiguration", {
        "tunnelIdentifier": c.tunnel_identifier,
        "pelletIdentifier": c.pellet_identifier
    })


def hardware_configuration_constructor(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode) -> HardwareConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return HardwareConfiguration(**humps.decamelize(content))
