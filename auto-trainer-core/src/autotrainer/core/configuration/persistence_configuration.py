from dataclasses import dataclass

import humps
from typing_extensions import Self
import yaml

from autotrainer.core import make_camelize_representer, make_decamelize_constructor


@dataclass
class PersistenceConfiguration:
    output_location: str = ""

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            output_location=content.get("output_location", "")
        )


persistence_configuration_representer = make_camelize_representer("!PersistenceConfiguration")
persistence_configuration_constructor = make_decamelize_constructor(PersistenceConfiguration)
