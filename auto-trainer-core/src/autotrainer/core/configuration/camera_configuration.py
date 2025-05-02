from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, Any

import humps
from typing_extensions import Self

import yaml


class CameraId(IntEnum, Enum):
    Left = 0,
    Right = 1,
    Web = 2


@dataclass
class CameraConfiguration:
    id: CameraId = CameraId.Left
    name: str = "(unnamed)"
    is_enabled: bool = False
    is_record_enabled: bool = False
    record_mode: int = 0
    is_still_image_capture_enabled: bool = False
    still_image_capture_interval: float = 5.0
    scheme: str = ""
    host: str = ""
    port: int = 0
    path: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_version_zero(cls, name: str, content: dict) -> Self:
        if name == "camera1":
            camera_id = CameraId.Left
        elif name == "camera2":
            camera_id = CameraId.Right
        else:
            camera_id = CameraId.Web

        if "camera" in content:
            camera = content["camera"]
        else:
            return None

        known_params = ["scheme", "host", "path", "port"]

        params = dict()

        for key in camera:
            if key not in known_params:
                params[key] = camera[key]

        return cls(
            id=camera_id,
            name=content.get("name", "(unnamed)"),
            is_enabled=content.get("is_enabled", False),
            is_record_enabled=content.get("is_record_enabled", False),
            record_mode=content.get("record_mode", 0),
            is_still_image_capture_enabled=content.get("is_still_image_capture_enabled", False),
            still_image_capture_interval=content.get("still_image_capture_interval", 0.0),
            scheme=camera.get("scheme", ""),
            host=camera.get("host", ""),
            port=camera.get("port", 0),
            path=camera.get("path", ""),
            params=params
        )


def camera_configuration_representer(dumper: yaml.SafeDumper, c: CameraConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!CameraConfiguration", {
        "id": c.id.value,
        "name": c.name,
        "isEnabled": c.is_enabled,
        "isRecordEnabled": c.is_record_enabled,
        "recordMode": c.record_mode,
        "isStillImageCaptureEnabled": c.is_still_image_capture_enabled,
        "stillImageCaptureInterval": c.still_image_capture_interval,
        "scheme": c.scheme,
        "host": c.host,
        "port": c.port,
        "path": c.path,
        "params": c.params
    })


def camera_configuration_constructor(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode) -> CameraConfiguration:
    content = humps.decamelize(loader.construct_mapping(node, deep=True))
    if "id" in content:
        content["id"] = CameraId(content["id"])
    return CameraConfiguration(**content)
