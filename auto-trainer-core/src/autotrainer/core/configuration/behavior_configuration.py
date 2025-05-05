from dataclasses import dataclass, field
from typing import Type
from typing_extensions import Self

import yaml
import humps

from ..analysis import LoadCellAutoTareConfiguration, load_cell_auto_tare_configuration_representer
from ..analysis import HeadbarPressureConfiguration, headbar_pressure_configuration_representer
from ..analysis import LoadCellConfiguration, load_cell_configuration_representer


@dataclass
class PelletDeliveryConfiguration:
    """
    Behavior model options related to pellet delivery.
    """
    is_enabled: bool = False
    is_pellet_cover_enabled: bool = False
    is_intersession_analysis_enabled: bool = False
    max_pellets_per_session: int = 10
    max_pellets_per_day: int = 50
    max_pellet_missing_seconds: float = 15.0

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            is_enabled=content.get("is_deliver_pellet_enabled", False),
            is_pellet_cover_enabled=content.get("is_cover_pellet_enabled", False),
            is_intersession_analysis_enabled=content.get("is_intersession_analysis_enabled", False),
            max_pellets_per_session=content.get("max_pellets_per_session", 10),
            max_pellets_per_day=content.get("max_pellets_per_day", 50),
            max_pellet_missing_seconds=content.get("max_pellet_missing_seconds", 15.0)
        )


@dataclass
class HeadClampConfiguration:
    """
    Behavior model options related to the head clamp magnet including standard intensity and auto-clamp actions.
    """
    min_baseline_intensity: float = 0.0
    max_baseline_intensity: float = 90.0
    baseline_intensity_increment: float = 10.0
    auto_clamp_intensity: float = 100.0
    auto_clamp_release_tone_freq: int = 7000
    auto_clamp_release_tone_delay: float = 0.1

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            min_baseline_intensity=content.get("min_baseline_intensity", 0.0),
            max_baseline_intensity=content.get("max_baseline_intensity", 90.0),
            baseline_intensity_increment=content.get("baseline_intensity_increment", 10.0),
            auto_clamp_intensity=content.get("auto_clamp_intensity", 100.0),
            auto_clamp_release_tone_freq=content.get("auto_clamp_release_tone_freq", 7000),
            auto_clamp_release_tone_delay=content.get("auto_clamp_release_tone_delay", 0.1)
        )


@dataclass
class BehaviorConfiguration:
    pellet_delivery: PelletDeliveryConfiguration = field(default_factory=PelletDeliveryConfiguration)
    head_clamp: HeadClampConfiguration = field(default_factory=HeadClampConfiguration)
    load_cell: LoadCellConfiguration = field(default_factory=LoadCellConfiguration)
    headbar_pressure: HeadbarPressureConfiguration = field(default_factory=HeadbarPressureConfiguration)
    auto_tare: LoadCellAutoTareConfiguration = field(default_factory=LoadCellAutoTareConfiguration)

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        configuration = cls()

        if "head_fix" in content:
            if "load_cell" in content["head_fix"]:
                configuration.load_cell = LoadCellConfiguration.from_version_zero(content["head_fix"]["load_cell"])
            if "headbar_pressure" in content["head_fix"]:
                configuration.headbar_pressure = HeadbarPressureConfiguration.from_version_zero(
                    content["head_fix"]["headbar_pressure"]
                )
            if "auto_tare" in content["head_fix"]:
                configuration.auto_tare = LoadCellAutoTareConfiguration.from_version_zero(
                    content["head_fix"]["auto_tare"])

        if "behavior" in content:
            configuration.head_clamp = HeadClampConfiguration.from_version_zero(content["behavior"])
            configuration.pellet_delivery = PelletDeliveryConfiguration.from_version_zero(content["behavior"])

        return configuration


def pellet_delivery_configuration_representer(dumper: yaml.SafeDumper,
                                              c: PelletDeliveryConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!PelletDeliveryConfiguration", {
        "isEnabled": c.is_enabled,
        "isPelletCoverEnabled": c.is_pellet_cover_enabled,
        "isIntersessionAnalysisEnabled": c.is_intersession_analysis_enabled,
        "maxPelletsPerSession": c.max_pellets_per_session,
        "maxPelletsPerDay": c.max_pellets_per_day,
        "maxPelletMissingSeconds": c.max_pellet_missing_seconds
    })


def head_clamp_configuration_representer(dumper: yaml.SafeDumper, c: HeadClampConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!HeadClampConfiguration", {
        "minBaselineIntensity": c.min_baseline_intensity,
        "maxBaselineIntensity": c.max_baseline_intensity,
        "baselineIntensityIncrement": c.baseline_intensity_increment,
        "autoClampIntensity": c.auto_clamp_intensity,
        "autoClampReleaseToneFreq": c.auto_clamp_release_tone_freq,
        "autoClampReleaseToneDelay": c.auto_clamp_release_tone_delay
    })


def behavior_configuration_representer(dumper: yaml.SafeDumper, c: BehaviorConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!BehaviorConfiguration", {
        "pelletDelivery": c.pellet_delivery,
        "headClamp": c.head_clamp,
        "loadCell": c.load_cell,
        "headbarPressure": c.headbar_pressure,
        "autoTare": c.auto_tare
    })


def add_behavior_configuration_representers(dumper: Type[yaml.SafeDumper]):
    dumper.add_representer(PelletDeliveryConfiguration, pellet_delivery_configuration_representer)
    dumper.add_representer(LoadCellConfiguration, load_cell_configuration_representer)
    dumper.add_representer(HeadClampConfiguration, head_clamp_configuration_representer)
    dumper.add_representer(HeadbarPressureConfiguration, headbar_pressure_configuration_representer)
    dumper.add_representer(LoadCellAutoTareConfiguration, load_cell_auto_tare_configuration_representer)

    dumper.add_representer(BehaviorConfiguration, behavior_configuration_representer)


def pellet_delivery_configuration_constructor(loader: yaml.SafeLoader,
                                              node: yaml.nodes.MappingNode) -> PelletDeliveryConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return PelletDeliveryConfiguration(**humps.decamelize(content))


def load_cell_configuration_constructor(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode) -> LoadCellConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return LoadCellConfiguration(**humps.decamelize(content))


def headbar_pressure_configuration_constructor(loader: yaml.SafeLoader,
                                               node: yaml.nodes.MappingNode) -> HeadbarPressureConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return HeadbarPressureConfiguration(**humps.decamelize(content))


def head_clamp_configuration_constructor(loader: yaml.SafeLoader,
                                         node: yaml.nodes.MappingNode) -> HeadClampConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return HeadClampConfiguration(**humps.decamelize(content))


def load_cell_auto_tare_configuration_constructor(loader: yaml.SafeLoader,
                                                  node: yaml.nodes.MappingNode) -> LoadCellAutoTareConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return LoadCellAutoTareConfiguration(**humps.decamelize(content))


def behavior_configuration_constructor(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode) -> BehaviorConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return BehaviorConfiguration(**humps.decamelize(content))


def add_behavior_configuration_constructors(safe_loader: Type[yaml.SafeLoader]):
    safe_loader.add_constructor("!BehaviorConfiguration", behavior_configuration_constructor)
    safe_loader.add_constructor("!PelletDeliveryConfiguration", pellet_delivery_configuration_constructor)
    safe_loader.add_constructor("!LoadCellConfiguration", load_cell_configuration_constructor)
    safe_loader.add_constructor("!HeadbarPressureConfiguration", headbar_pressure_configuration_constructor)
    safe_loader.add_constructor("!HeadClampConfiguration", head_clamp_configuration_constructor)
    safe_loader.add_constructor("!LoadCellAutoTareConfiguration", load_cell_auto_tare_configuration_constructor)
