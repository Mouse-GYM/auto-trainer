from dataclasses import dataclass

import humps
from typing_extensions import Self
import yaml


@dataclass
class PersistenceConfiguration:
    output_location: str = ""

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            output_location=content.get("output_location", "")
        )


def persistence_configuration_representer(dumper: yaml.SafeDumper,
                                          c: PersistenceConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!PersistenceConfiguration", {
        "outputLocation": c.output_location,
    })


def persistence_configuration_constructor(loader: yaml.SafeLoader,
                                          node: yaml.nodes.MappingNode) -> PersistenceConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return PersistenceConfiguration(**humps.decamelize(content))
