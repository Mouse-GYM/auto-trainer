import dataclasses
from dataclasses import dataclass, field
from typing import Type
from typing_extensions import Self

import yaml

from .. import build_kwargs_apply_mapping, make_camelize_representer, make_decamelize_constructor
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
    is_intersession_pellet_shift_enabled: bool = True
    max_pellets_per_session: int = 10
    max_pellets_per_day: int = 50

    max_pellet_missing_seconds: float = 1.0  # duration after which we consider pellet missing and do a load pellet

    auto_correct_motors_drift: bool = False
    use_triangle_pellet_distance_too_far: bool = False
    triangle_pellet_expected_distance: float = 5  # mm
    triangle_pellet_diff_too_far_threshold: float = 1  # mm

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(**build_kwargs_apply_mapping(content, (
            *(f.name for f in dataclasses.fields(cls)),
            ('is_enabled', 'is_deliver_pellet_enabled'),
            ('is_pellet_cover_enabled', 'is_cover_pellet_enabled'),
        ), skip_remaining=True))


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
    auto_clamp_no_activity_release_delay: float = 30
    auto_clamp_release_load_count: int = 100_000

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(**build_kwargs_apply_mapping(
            content,
            tuple(f.name for f in dataclasses.fields(cls)),
            skip_remaining=True,
        ))


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

    @classmethod
    def from_version_one(cls, content):
        return cls(
            load_cell=LoadCellConfiguration.from_version_one(content.get("load_cell", {})),
            headbar_pressure=HeadbarPressureConfiguration(**content.get("headbar_pressure", {})),
            auto_tare=LoadCellAutoTareConfiguration(**content.get("auto_tare", {})),
            head_clamp=HeadClampConfiguration(**content.get("head_clamp", {})),
            pellet_delivery=PelletDeliveryConfiguration(**content.get("pellet_delivery", {})),
        )


pellet_delivery_configuration_representer = make_camelize_representer("!PelletDeliveryConfiguration")
head_clamp_configuration_representer = make_camelize_representer("!HeadClampConfiguration")
behavior_configuration_representer = make_camelize_representer("!BehaviorConfiguration")


def add_behavior_configuration_representers(dumper: Type[yaml.SafeDumper]):
    dumper.add_representer(PelletDeliveryConfiguration, pellet_delivery_configuration_representer)
    dumper.add_representer(LoadCellConfiguration, load_cell_configuration_representer)
    dumper.add_representer(HeadClampConfiguration, head_clamp_configuration_representer)
    dumper.add_representer(HeadbarPressureConfiguration, headbar_pressure_configuration_representer)
    dumper.add_representer(LoadCellAutoTareConfiguration, load_cell_auto_tare_configuration_representer)
    dumper.add_representer(BehaviorConfiguration, behavior_configuration_representer)


pellet_delivery_configuration_constructor = make_decamelize_constructor(PelletDeliveryConfiguration)
load_cell_configuration_constructor = make_decamelize_constructor(LoadCellConfiguration)
headbar_pressure_configuration_constructor = make_decamelize_constructor(HeadbarPressureConfiguration)
head_clamp_configuration_constructor = make_decamelize_constructor(HeadClampConfiguration)
load_cell_auto_tare_configuration_constructor = make_decamelize_constructor(LoadCellAutoTareConfiguration)
behavior_configuration_constructor = make_decamelize_constructor(BehaviorConfiguration)


def add_behavior_configuration_constructors(safe_loader: Type[yaml.SafeLoader]):
    safe_loader.add_constructor("!BehaviorConfiguration", behavior_configuration_constructor)
    safe_loader.add_constructor("!PelletDeliveryConfiguration", pellet_delivery_configuration_constructor)
    safe_loader.add_constructor("!LoadCellConfiguration", load_cell_configuration_constructor)
    safe_loader.add_constructor("!HeadbarPressureConfiguration", headbar_pressure_configuration_constructor)
    safe_loader.add_constructor("!HeadClampConfiguration", head_clamp_configuration_constructor)
    safe_loader.add_constructor("!LoadCellAutoTareConfiguration", load_cell_auto_tare_configuration_constructor)
