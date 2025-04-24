from dataclasses import dataclass, field
from typing import Type

import humps
from typing_extensions import Self
import yaml


@dataclass
class PelletDeliveryConfiguration:
    """
    Behavior model options related to pellet delivery.
    """
    is_enabled: bool = False
    is_pellet_cover_enabled: bool = False
    max_pellets_per_session: int = 10
    max_pellets_per_day: int = 50
    max_pellet_missing_seconds: float = 15.0

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            is_enabled=content.get("is_deliver_pellet_enabled", False),
            is_pellet_cover_enabled=content.get("is_cover_pellet_enabled", False),
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
class LoadCellConfiguration:
    load_trigger: int = 15
    min_load_on_duration: float = 0.25
    min_event_duration: float = 5.0
    min_load_off_duration: float = 2.0

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            load_trigger=content.get("load_trigger", 15),
            min_load_on_duration=content.get("min_load_on_duration", 0.25),
            min_event_duration=content.get("min_event_duration", 5.0),
            min_load_off_duration=content.get("min_load_off_duration", 2.0)
        )


@dataclass
class HeadbarPressureConfiguration:
    threshold: int = 20
    duration: float = 0.5

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            threshold=content.get("threshold", 20),
            duration=content.get("duration", 0.5)
        )


@dataclass
class AutoTareConfiguration:
    threshold: float = 0.1
    range_threshold: float = 0.75
    duration: float = 2.0

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            threshold=content.get("threshold", 0.1),
            range_threshold=content.get("range_threshold", 0.75),
            duration=content.get("duration", 2.0)
        )


@dataclass
class BehaviorConfiguration:
    pellet_delivery: PelletDeliveryConfiguration = field(default_factory=PelletDeliveryConfiguration)
    head_clamp: HeadClampConfiguration = field(default_factory=HeadClampConfiguration)
    load_cell: LoadCellConfiguration = field(default_factory=LoadCellConfiguration)
    headbar_pressure: HeadbarPressureConfiguration = field(default_factory=HeadbarPressureConfiguration)
    auto_tare: AutoTareConfiguration = field(default_factory=AutoTareConfiguration)

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
                configuration.auto_tare = AutoTareConfiguration.from_version_zero(content["head_fix"]["auto_tare"])

        if "behavior" in content:
            configuration.head_clamp = HeadClampConfiguration.from_version_zero(content["behavior"])
            configuration.pellet_delivery = PelletDeliveryConfiguration.from_version_zero(content["behavior"])

        return configuration


def pellet_delivery_configuration_representer(dumper: yaml.SafeDumper,
                                              c: PelletDeliveryConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!PelletDeliveryConfiguration", {
        "isEnabled": c.is_enabled,
        "isPelletCoverEnabled": c.is_pellet_cover_enabled,
        "maxPelletsPerSession": c.max_pellets_per_session,
        "maxPelletsPerDay": c.max_pellets_per_day,
        "maxPelletMissingSeconds": c.max_pellet_missing_seconds
    })


def load_cell_configuration_representer(dumper: yaml.SafeDumper, c: LoadCellConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!LoadCellConfiguration", {
        "loadTrigger": c.load_trigger,
        "minLoadOnDuration": c.min_load_on_duration,
        "minEventDuration": c.min_event_duration,
        "minLoadOffDuration": c.min_load_off_duration
    })


def headbar_pressure_configuration_representer(dumper: yaml.SafeDumper,
                                               c: HeadbarPressureConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!HeadbarPressureConfiguration", {
        "threshold": c.threshold,
        "duration": c.duration
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


def auto_tare_configuration_representer(dumper: yaml.SafeDumper, c: AutoTareConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!AutoTareConfiguration", {
        "threshold": c.threshold,
        "rangeThreshold": c.range_threshold,
        "duration": c.duration
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
    dumper.add_representer(AutoTareConfiguration, auto_tare_configuration_representer)

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


def auto_tare_configuration_constructor(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode) -> AutoTareConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return AutoTareConfiguration(**humps.decamelize(content))


def behavior_configuration_constructor(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode) -> BehaviorConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return BehaviorConfiguration(**humps.decamelize(content))


def add_behavior_configuration_constructors(safe_loader: yaml.SafeLoader):
    safe_loader.add_constructor("!BehaviorConfiguration", behavior_configuration_constructor)
    safe_loader.add_constructor("!PelletDeliveryConfiguration", pellet_delivery_configuration_constructor)
    safe_loader.add_constructor("!LoadCellConfiguration", load_cell_configuration_constructor)
    safe_loader.add_constructor("!HeadbarPressureConfiguration", headbar_pressure_configuration_constructor)
    safe_loader.add_constructor("!HeadClampConfiguration", head_clamp_configuration_constructor)
    safe_loader.add_constructor("!AutoTareConfiguration", auto_tare_configuration_constructor)
