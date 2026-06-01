import dataclasses
import enum
from datetime import date
from dataclasses import dataclass, field
from typing import Type, Optional, Dict
from typing_extensions import Self

import yaml

from autotrainer.core.logging import get_verbose_logger
from .animal_presence_configuration import GlobalAnimalPresenceConfig
from .autoclamp_evasion_config import AutoClampEvasionDetectorConfig
from .external_doors_monitor_configuration import ExternalDoorsMonitorConfig
from .presence_detection_configuration import PresenceDetectionConfig
from .system_fault_config import SystemFaultConfig
from .system_maintenance_config import SystemMaintenanceConfig
from .. import build_kwargs_apply_mapping, make_camelize_representer, make_decamelize_constructor, Offset3DTuple

from ..analysis import HeadbarPressureConfiguration
from .load_cell_config import LoadCellConfiguration, LoadCellAutoTareConfiguration
from ..analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitorConfig
from .alarm_configuration import EmergencyAlarmConfiguration
from ..analysis.auto_tunnel_fan_monitor import AutoTunnelSweepConfiguration
from ..analysis.autoclamp_evasion_detector import AutoClampEvasionDetector

logger = get_verbose_logger(__name__)


@dataclasses.dataclass
class ShiftXYZTarget:

    # should be in Diamond coordinate system
    x: float = 1.5
    y: float = -3
    z: float = 1


def default_shift_xyz_target() -> Offset3DTuple:
    return Offset3DTuple(**dataclasses.asdict(ShiftXYZTarget()))


def default_tongue_eaten_shift() -> Offset3DTuple:
    return Offset3DTuple(0, 0.5, 0)


@dataclasses.dataclass
class _ShiftXYZBufferHandlerConfig:

    minimum_reach_fail: int = 10  # minimum nbr of failed reach, to make the mean/an entire processing of them
    target: Offset3DTuple = field(default_factory=default_shift_xyz_target)


@dataclasses.dataclass
class ShiftXYZBufferHandlerConfig(_ShiftXYZBufferHandlerConfig):

    def __init__(self, **kwargs):
        for c in "xyz":
            kwargs.pop(f"target_{c}", None)  # old config
        super().__init__(**kwargs)


@dataclasses.dataclass
class ShiftXYZHandlerConfig:

    use_tongue_eaten: bool = True
    tongue_eaten_shift: Offset3DTuple = field(default_factory=default_tongue_eaten_shift)

    use_reach_buffer: bool = True
    selected: str = "ShiftXYZBufferHandler"
    buffer: ShiftXYZBufferHandlerConfig = field(default_factory=ShiftXYZBufferHandlerConfig)


@dataclass
class AutoCloseGateOnIntersessionConfiguration:

    enabled: bool = False  # enabled/disabled
    session_min_duration: float = 5  # do not try close gate if session duration shorter than this
    delay_after_cage_enter: float = 2.5  # only close gate once this delay since cage enter has elapsed


@dataclass
class HomeOnExcessiveDriftDistanceConfiguration:
    """Execute, when in monitoring (should equal to be in deliver position), home to reset motors if measured drift distance is higher than threshold"""

    enabled: bool = False
    excessive_distance_threshold: float = 5  # mm

    min_samples: int = 30
    # only considerate if/when nbr of samples is greater than this.
    # This can compensate small unsync between inference results and motor status positions,
    # when the start of the sampling would be done right after the pellet-arm finished moving.
    # The current inference is giving us ~15 datapoints per second,
    # and almost same for the motor status position: ~10 / sec.
    # So this requires/takes ~2 seconds of duration to get what's necessary.


@dataclass
class PelletUncoverConfiguration:
    min_y_dcs: float = 0  # mm,  minimum Y dcs for all hand parts to be "valid" for uncover
    trigger_delay: float = 1  # seconds, duration before real active/trigger to uncover when it's "valid"


@dataclass
class PelletDeliveryConfiguration:
    """
    Behavior model options related to pellet delivery.
    """

    is_enabled: bool = False
    """When disabled not automatic behavior movement will be peformed, but eventually on application start"""

    is_pellet_cover_enabled: bool = False
    """If enabled: cover pellet when session starts, and wait uncover condition"""

    # not really related to pellet delivery but has been here since start:
    is_intersession_analysis_enabled: bool = False
    is_intersession_pellet_shift_enabled: bool = True

    max_pellets_per_session: int = 10  # actually unused
    max_pellets_per_day: int = 50  # actually unused
    max_pellet_missing_seconds: float = 1.0  # how long to wait before load pellet when pellet missing/not seen
    # this help ensure we don't execute a load pellet if we get an incorrect pose_result with pellet seen == False,
    # which can happen eventually (missed inference detection basically).

    auto_correct_motors_drift: bool = False  # attempt "live" motor drift correction -- DISABLED in code

    use_triangle_pellet_distance_too_far: bool = False
    """If enabled then a triangle-pellet too far distance also trigger a load-pellet"""
    triangle_pellet_expected_distance: float = 5  # mm
    triangle_pellet_diff_too_far_threshold: float = 1  # mm

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(**build_kwargs_apply_mapping(content, (
            *(f.name for f in dataclasses.fields(cls)),
            ('is_enabled', 'is_deliver_pellet_enabled'),
            ('is_pellet_cover_enabled', 'is_cover_pellet_enabled'),
        ), skip_remaining=True))


class HeadClampReleaseMode(str, enum.Enum):
    ACTIVITY = "Activity"
    FIXED_DURATION = "Fixed duration"


@dataclass
class HeadClampConfiguration:
    """
    Behavior model options related to the head clamp magnet including standard intensity and auto-clamp actions.
    """

    enabled: bool = False
    baseline_intensity: float = 0.0
    auto_clamp_intensity: float = 100.0
    auto_clamp_release_tone_freq: int = 7000
    auto_clamp_release_tone_delay: float = 0.1
    before_reengage_delay: float = 5  # how long to wait/delay before allow/execute a re-engage after a disengage.

    prerelease_intensity: float = 70  # absolute % value
    prerelease_duration: float = 0  # seconds, if 0 then this pre-release is disabled / does not occur.

    release_mode: str = HeadClampReleaseMode.ACTIVITY.value

    # HeadClampReleaseMode.ACTIVITY
    auto_clamp_no_activity_release_delay: float = 30  # seconds
    auto_clamp_release_load_count: int = 100_000

    # HeadClampReleaseMode.FIXED_DURATION
    fixed_duration_release_delay: float = 30  # seconds


    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(**build_kwargs_apply_mapping(
            content,
            tuple(f.name for f in dataclasses.fields(cls)),
            skip_remaining=True,
        ))


@dataclasses.dataclass
class AutoEndSessionConfiguration:
    # enabled: bool = True

    no_activity_delay_minutes: int = 1
    """This is only for the Nose part. If it's not seen that much duration consecutively, 
     then also auto-end session"""

    animal_tunnel_no_activity_delay: float = 10  # seconds
    """Delay without tunnel animal activity (== any animal part seen *and* low load-cell variance)
     which triggers auto-end session"""


@dataclasses.dataclass
class BatchSessionRecordingConfiguration:

    enabled: bool = False

    maximum_batch_size: int = 0
    """If 0: no max batch size, otherwise, once batch is over the size: force batch session processing"""


@dataclass
class CageCleaningConfig:

    clean_days_interval: int = 14


@dataclass
class _BehaviorConfiguration:
    pellet_delivery: PelletDeliveryConfiguration = field(default_factory=PelletDeliveryConfiguration)
    pellet_uncover: PelletUncoverConfiguration = field(default_factory=PelletUncoverConfiguration)
    shift_xyz_handler: ShiftXYZHandlerConfig = field(default_factory=ShiftXYZHandlerConfig)
    head_clamp: HeadClampConfiguration = field(default_factory=HeadClampConfiguration)
    load_cell: LoadCellConfiguration = field(default_factory=LoadCellConfiguration)
    headbar_pressure: HeadbarPressureConfiguration = field(default_factory=HeadbarPressureConfiguration)
    auto_tare: LoadCellAutoTareConfiguration = field(default_factory=LoadCellAutoTareConfiguration)
    audio: AudioSpectrumThrashMonitorConfig = field(default_factory=AudioSpectrumThrashMonitorConfig)
    global_animal_presence: GlobalAnimalPresenceConfig = field(default_factory=GlobalAnimalPresenceConfig)
    emergency_alarm: EmergencyAlarmConfiguration = field(default_factory=EmergencyAlarmConfiguration)
    external_doors: ExternalDoorsMonitorConfig = field(default_factory=ExternalDoorsMonitorConfig)
    topcam_presence_detection: PresenceDetectionConfig = field(default_factory=PresenceDetectionConfig)
    auto_end_session: AutoEndSessionConfiguration = field(default_factory=AutoEndSessionConfiguration)
    auto_tunnel_sweep: AutoTunnelSweepConfiguration = field(default_factory=AutoTunnelSweepConfiguration)
    batch_session_recording: BatchSessionRecordingConfiguration = field(default_factory=BatchSessionRecordingConfiguration)
    auto_close_gate_on_intersession: AutoCloseGateOnIntersessionConfiguration = field(default_factory=AutoCloseGateOnIntersessionConfiguration)
    home_on_excessive_drift_distance: HomeOnExcessiveDriftDistanceConfiguration = field(default_factory=HomeOnExcessiveDriftDistanceConfiguration)
    system_maintenance: SystemMaintenanceConfig = field(default_factory=SystemMaintenanceConfig)
    system_fault: SystemFaultConfig = field(default_factory=SystemFaultConfig)
    cage_cleaning: CageCleaningConfig = field(default_factory=CageCleaningConfig)
    autoclamp_evasion_detector: AutoClampEvasionDetectorConfig = field(default_factory=AutoClampEvasionDetectorConfig)

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
    def from_version_one(cls, content: Dict):
        headclamp = content.get("head_clamp", {})
        headclamp.pop('max_baseline_intensity')
        headclamp.pop('baseline_intensity_increment')
        baseline = headclamp.pop('min_baseline_intensity')
        if baseline is not None:
            headclamp['baseline_intensity'] = baseline
        return cls(
            load_cell=LoadCellConfiguration.from_version_one(content.get("load_cell", {})),
            headbar_pressure=HeadbarPressureConfiguration(**content.get("headbar_pressure", {})),
            auto_tare=LoadCellAutoTareConfiguration(**content.get("auto_tare", {})),
            head_clamp=HeadClampConfiguration(**headclamp),
            pellet_delivery=PelletDeliveryConfiguration(**content.get("pellet_delivery", {})),
        )


@dataclasses.dataclass
class BehaviorConfiguration(_BehaviorConfiguration):
    # NB: having to subclass _BehaviorConfiguration dataclass type to allow to customize init signature (and body):

    def __init__(self,
                 *,
                 mouse_presence=None,  # temporarily to be back-compatible with previous
                 **kwargs):
        if mouse_presence is not None:
            logger.notice("Dropping previous mouse_presence config, new default one will be used. dropped entry: %s",
                          mouse_presence)
        super().__init__(**kwargs)


_tag_2_cls = dict(
    PelletDeliveryConfiguration=PelletDeliveryConfiguration,
    PelletUncoverConfiguration=PelletUncoverConfiguration,
    LoadCellConfiguration=LoadCellConfiguration,
    HeadClampConfiguration=HeadClampConfiguration,
    HeadbarPressureConfiguration=HeadbarPressureConfiguration,
    LoadCellAutoTareConfiguration=LoadCellAutoTareConfiguration,
    BehaviorConfiguration=BehaviorConfiguration,
    AudioMonitorConfiguration=AudioSpectrumThrashMonitorConfig,
    AnimalPresenceConfiguration=GlobalAnimalPresenceConfig,
    EmergencyAlarmConfiguration=EmergencyAlarmConfiguration,
    PresenceDetectionConfiguration=PresenceDetectionConfig,
    ExternalDoorsMonitorConfiguration=ExternalDoorsMonitorConfig,
    AutoEndSessionConfiguration=AutoEndSessionConfiguration,
    AutoTunnelSweepConfiguration=AutoTunnelSweepConfiguration,
    BatchSessionRecordingConfiguration=BatchSessionRecordingConfiguration,
    AutoCloseGateOnIntersessionConfiguration=AutoCloseGateOnIntersessionConfiguration,
    HomeOnExcessiveDriftDistance=HomeOnExcessiveDriftDistanceConfiguration,  # missed Configuration suffix
    # ShiftXYZTarget="ShiftXYZTarget",  # replaced by Offset3dTuple.
    ShiftXYZHandlerConfiguration=ShiftXYZHandlerConfig,
    ShiftXYZBufferHandlerConfiguration=ShiftXYZBufferHandlerConfig,
    SystemMaintenanceConfig=SystemMaintenanceConfig,
    SystemFaultConfig=SystemFaultConfig,
    CageCleaningConfig=CageCleaningConfig,
)


def add_behavior_configuration_representers(dumper: Type[yaml.SafeDumper]):
    def add(klass, tagname):
        dumper.add_representer(klass, make_camelize_representer(f"!{tagname}"))

    for tag, cls in _tag_2_cls.items():
        add(cls, tag)

    from autotrainer.core.configuration import repr_offset3d_tuple

    dumper.add_representer(ShiftXYZTarget, repr_offset3d_tuple)
    # changed to use Offset3dTuple


def add_behavior_configuration_constructors(safe_loader: Type[yaml.SafeLoader]):

    def add(klass, tagname):
        safe_loader.add_constructor(f"!{tagname}", make_decamelize_constructor(klass))

    for tag, cls in _tag_2_cls.items():
        add(cls, tag)

    add(GlobalAnimalPresenceConfig, "MousePresenceConfiguration")
    # keeping temporarily MousePresenceConfiguration, was renamed to AnimalPresenceConfiguration. Back-compatibility.
    # todo: remove some when later.
    #
