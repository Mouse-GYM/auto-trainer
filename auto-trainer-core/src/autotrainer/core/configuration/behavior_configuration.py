import dataclasses
from dataclasses import dataclass, field
from typing import Type, Optional, Dict
from typing_extensions import Self

import yaml

from autotrainer.core.logging import get_verbose_logger
from .animal_presence_configuration import GlobalAnimalPresenceConfig
from .external_doors_monitor_configuration import ExternalDoorsMonitorConfig
from .presence_detection_configuration import PresenceDetectionConfig
from .. import build_kwargs_apply_mapping, make_camelize_representer, make_decamelize_constructor
from ..analysis import LoadCellAutoTareConfiguration, load_cell_auto_tare_configuration_representer
from ..analysis import HeadbarPressureConfiguration, headbar_pressure_configuration_representer
from ..analysis import LoadCellConfiguration, load_cell_configuration_representer
from ..analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitorConfig
from .alarm_configuration import EmergencyAlarmConfiguration


logger = get_verbose_logger(__name__)



@dataclass
class AutoCloseGateOnIntersessionConfiguration:

    enabled: bool = False  # enabled/disabled
    session_min_duration: float = 5  # do not try close gate if session duration shorter than this
    delay_after_cage_enter: float = 2.5  # only close gate once this delay since cage enter has elapsed


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
    max_pellet_missing_seconds: float = 1.0  # how long to wait before load pellet when pellet missing/not seen
    # this help ensure we don't execute a load pellet if we get an incorrect pose_result with pellet seen == False,
    # which can happen eventually (missed inference detection basically).
    pellet_hand_uncover_distance: Optional[float] = 5  # mm ; None means disabled.

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
class _BehaviorConfiguration:
    pellet_delivery: PelletDeliveryConfiguration = field(default_factory=PelletDeliveryConfiguration)
    head_clamp: HeadClampConfiguration = field(default_factory=HeadClampConfiguration)
    load_cell: LoadCellConfiguration = field(default_factory=LoadCellConfiguration)
    headbar_pressure: HeadbarPressureConfiguration = field(default_factory=HeadbarPressureConfiguration)
    auto_tare: LoadCellAutoTareConfiguration = field(default_factory=LoadCellAutoTareConfiguration)
    audio: AudioSpectrumThrashMonitorConfig = field(default_factory=AudioSpectrumThrashMonitorConfig)
    global_animal_presence: GlobalAnimalPresenceConfig = field(default_factory=GlobalAnimalPresenceConfig)
    emergency_alarm: EmergencyAlarmConfiguration = field(default_factory=EmergencyAlarmConfiguration)
    external_doors: ExternalDoorsMonitorConfig = field(default_factory=ExternalDoorsMonitorConfig)
    topcam_presence_detection: PresenceDetectionConfig = field(default_factory=PresenceDetectionConfig)

    @classmethod
    def from_version_zero(cls, content: Dict) -> Self:
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


class BehaviorConfiguration(_BehaviorConfiguration):
    # NB: having to subclass _BehaviorConfiguration dataclass type to allow customize init signature (and body):

    def __init__(self,
                 *,
                 mouse_presence=None,  # temporarily to be back-compatible with previous
                 **kwargs):
        if mouse_presence is not None:
            logger.notice("Dropping previous mouse_presence config, new default one will be used. dropped entry: %s",
                          mouse_presence)
        super().__init__(**kwargs)


pellet_delivery_configuration_representer = make_camelize_representer("!PelletDeliveryConfiguration")
head_clamp_configuration_representer = make_camelize_representer("!HeadClampConfiguration")
behavior_configuration_representer = make_camelize_representer("!BehaviorConfiguration")
audio_monitor_representer = make_camelize_representer("!AudioMonitorConfiguration")
animal_presence_monitor_representer = make_camelize_representer("!AnimalPresenceConfiguration")
emergency_alarm_representer = make_camelize_representer("!EmergencyAlarmConfiguration")


def add_behavior_configuration_representers(dumper: Type[yaml.SafeDumper]):
    dumper.add_representer(PelletDeliveryConfiguration, pellet_delivery_configuration_representer)
    dumper.add_representer(LoadCellConfiguration, load_cell_configuration_representer)
    dumper.add_representer(HeadClampConfiguration, head_clamp_configuration_representer)
    dumper.add_representer(HeadbarPressureConfiguration, headbar_pressure_configuration_representer)
    dumper.add_representer(LoadCellAutoTareConfiguration, load_cell_auto_tare_configuration_representer)
    dumper.add_representer(BehaviorConfiguration, behavior_configuration_representer)
    dumper.add_representer(AudioSpectrumThrashMonitorConfig, audio_monitor_representer)
    dumper.add_representer(GlobalAnimalPresenceConfig, animal_presence_monitor_representer)
    dumper.add_representer(EmergencyAlarmConfiguration, emergency_alarm_representer)
    dumper.add_representer(PresenceDetectionConfig, make_camelize_representer("!PresenceDetectionConfiguration"))
    dumper.add_representer(ExternalDoorsMonitorConfig, make_camelize_representer("!ExternalDoorsMonitorConfiguration"))


pellet_delivery_configuration_constructor = make_decamelize_constructor(PelletDeliveryConfiguration)
load_cell_configuration_constructor = make_decamelize_constructor(LoadCellConfiguration)
headbar_pressure_configuration_constructor = make_decamelize_constructor(HeadbarPressureConfiguration)
head_clamp_configuration_constructor = make_decamelize_constructor(HeadClampConfiguration)
load_cell_auto_tare_configuration_constructor = make_decamelize_constructor(LoadCellAutoTareConfiguration)
behavior_configuration_constructor = make_decamelize_constructor(BehaviorConfiguration)
audio_monitor_configuration_constructor = make_decamelize_constructor(AudioSpectrumThrashMonitorConfig)
animal_presence_configuration_constructor = make_decamelize_constructor(GlobalAnimalPresenceConfig)
emergency_alarm_configuration_constructor = make_decamelize_constructor(EmergencyAlarmConfiguration)


def add_behavior_configuration_constructors(safe_loader: Type[yaml.SafeLoader]):
    safe_loader.add_constructor("!BehaviorConfiguration", behavior_configuration_constructor)
    safe_loader.add_constructor("!PelletDeliveryConfiguration", pellet_delivery_configuration_constructor)
    safe_loader.add_constructor("!LoadCellConfiguration", load_cell_configuration_constructor)
    safe_loader.add_constructor("!HeadbarPressureConfiguration", headbar_pressure_configuration_constructor)
    safe_loader.add_constructor("!HeadClampConfiguration", head_clamp_configuration_constructor)
    safe_loader.add_constructor("!LoadCellAutoTareConfiguration", load_cell_auto_tare_configuration_constructor)
    safe_loader.add_constructor("!AudioMonitorConfiguration", audio_monitor_configuration_constructor)
    #
    safe_loader.add_constructor("!AnimalPresenceConfiguration", animal_presence_configuration_constructor)
    safe_loader.add_constructor("!MousePresenceConfiguration", animal_presence_configuration_constructor)
    # keeping temporarily MousePresenceConfiguration, was renamed to AnimalPresenceConfiguration. Back-compatibility.
    # todo: remove some when later.
    #
    safe_loader.add_constructor("!EmergencyAlarmConfiguration", emergency_alarm_configuration_constructor)
    safe_loader.add_constructor("!PresenceDetectionConfiguration", make_decamelize_constructor(PresenceDetectionConfig))
    safe_loader.add_constructor("!ExternalDoorsMonitorConfiguration", make_decamelize_constructor(ExternalDoorsMonitorConfig))
