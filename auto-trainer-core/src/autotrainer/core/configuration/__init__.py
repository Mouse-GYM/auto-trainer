from __future__ import annotations

import yaml


from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


DEFAULT_3D_CALIB_DIR_NAME = "4mm_6r_8c_4x"


def generic_constructor(loader, tag, node):
    cls_name = node.__class__.__name__
    if cls_name == "SequenceNode":
        return loader.construct_sequence(node)
    elif cls_name == "MappingNode":
        return loader.construct_mapping(node)
    else:
        return loader.construct_scalar(node)


class GenericSafeLoader(yaml.SafeLoader):
    pass


yaml.add_multi_constructor("", generic_constructor, Loader=GenericSafeLoader)

#

class SystemConfigurationLoader(yaml.SafeLoader):
    """Dedicated yaml loader for SystemConfiguration"""
    safe_load: bool = False


class SystemConfigurationSafeLoader(SystemConfigurationLoader):

    safe_load = True

    def ignore_unknown(self, suffix, node):
        logger.warning("Skipping/ignoring tag/section %s", suffix)
        return None


def _ignore_unknown(loader, suffix, node):
    return loader.ignore_unknown(suffix, node)


# allow to ignore unknown tags:
SystemConfigurationSafeLoader.add_multi_constructor('', _ignore_unknown)
SystemConfigurationSafeLoader.add_multi_constructor('!', _ignore_unknown)


#

class SystemConfigurationDumper(yaml.SafeDumper):
    """Dedicated yaml dumper for SystemConfiguration"""


# above must be before below


from .behavior_configuration import BehaviorConfiguration
from .camera_configuration import CameraConfiguration, CameraId
from .hardware_configuration import HardwareConfiguration
from .inference_configuration import InferenceConfiguration
from .persistence_configuration import PersistenceConfiguration
from .system_configuration import SystemConfiguration
