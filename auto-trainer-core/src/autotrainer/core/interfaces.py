import enum
from typing import Callable, List, Protocol, Optional, TypeVar
from uuid import UUID

from autotrainer.core import Offset3DTuple
from autotrainer.core.reach_event import ReachEvent


class CaptureAnalysisResult(str, enum.Enum):
    CAPTURE_ONLY = "capture_only"
    ANALYSIS_SUCCEEDED = "analysis_succeeded"
    ANALYSIS_FAILED = "analysis_failed"
    ANALYSIS_DELAYED = "analysis_delayed"


class RecordingEndingReason(str, enum.Enum):
    NA = "NA"
    ALGO_PAUSED = "AlgoPaused"
    EXIT_TUNNEL = "ExitTunnel"
    PELLET_LOADING = "PelletLoading"
    MISSING_ANIMAL_ACTIVITY_TIMEOUT = "MissingAnimalActivityTimeout"
    MOTOR_DRIFT_HOMING = "MotorDriftHoming"


HandlerT = TypeVar("HandlerT", bound=Callable[..., None])
from typing_extensions import Self


class EventHandler(Protocol[HandlerT]):
    def __iadd__(self, handler: HandlerT) -> Self: ...

    def __isub__(self, handler: HandlerT) -> Self: ...


class BehaviorAlgorithmProtocol(Protocol):
    @property
    def pellet_delivery_enabled(self) -> bool: ...

    @pellet_delivery_enabled.setter
    def pellet_delivery_enabled(self, value: bool) -> None: ...

    @property
    def pellet_cover_enabled(self) -> bool: ...

    @pellet_cover_enabled.setter
    def pellet_cover_enabled(self, value: bool) -> None: ...

    @property
    def intersession_pellet_shift_enabled(self) -> bool: ...

    @intersession_pellet_shift_enabled.setter
    def intersession_pellet_shift_enabled(self, value: bool) -> None: ...

    @property
    def pellet_hands_min_distance(self) -> float: ...

    @pellet_hands_min_distance.setter
    def pellet_hands_min_distance(self, value: float) -> None: ...

    @property
    def head_fixation_enabled(self) -> bool: ...

    @head_fixation_enabled.setter
    def head_fixation_enabled(self, value: bool) -> None: ...

    @property
    def auto_clamp_no_activity_release_delay(self) -> float: ...

    @auto_clamp_no_activity_release_delay.setter
    def auto_clamp_no_activity_release_delay(self, value: float) -> None: ...

    @property
    def auto_clamp_release_load_count(self) -> int: ...

    @auto_clamp_release_load_count.setter
    def auto_clamp_release_load_count(self, value: int) -> None: ...

    @property
    def baseline_intensity(self) -> int: ...

    @property
    def trial_reaches(self) -> List[ReachEvent]: ...

    def reset_configuration(self) -> None: ...

    @property
    def session_starting(self) -> EventHandler[Callable[[], None]]: ...

    @property
    def session_capture_ending(self) -> EventHandler[Callable[[RecordingEndingReason], None]]: ...

    @property
    def session_ending(self) -> EventHandler[Callable[[CaptureAnalysisResult], None]]: ...

    @property
    def pellets_presented_evt(self) -> EventHandler[Callable[[int], None]]: ...

    @property
    def pellets_consumed_evt(self) -> EventHandler[Callable[[int], None]]: ...

    @property
    def successful_reaches_evt(self) -> EventHandler[Callable[[int], None]]: ...

    @property
    def total_reaches_evt(self) -> EventHandler[Callable[[int], None]]: ...


class PelletHardwareProtocol(Protocol):
    def delay(self, amount: float):
        """Request to delay that amount of seconds"""

    @property
    def last_set_position(self) -> Optional[Offset3DTuple]:
        """Give the last SET position (deliver position, used with SEND_PELLET command"""

    @property
    def last_position(self) -> Optional[Offset3DTuple]:
        """Given the last actual position"""

    @property
    def last_dcs_set_position(self) -> Optional[Offset3DTuple]:
        """Give the last SET position, in DCS, (deliver position), used with SEND_PELLET command"""

    @property
    def last_dcs_position(self) -> Optional[Offset3DTuple]:
        """Given the last actual, in DCS, triangle position"""

    def set_x(self, value: float, *, absolute: bool = True, sender: str = "NA") -> Optional[UUID]:
        """
        Change the X stepper location and set it as the X-axis pellet release location.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def set_y(self, value: float, *, absolute: bool = True, sender: str = "NA") -> Optional[UUID]:
        """
        Change the Y stepper location and set it as the Y-axis pellet release location.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def set_z(self, value: float, *, absolute: bool = True, sender: str = "NA") -> Optional[UUID]:
        """
        Change the Z stepper location and set it as the Z-axis pellet release location.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def set_dcs_x(self, value: float, *, absolute: bool = True, sender: str = "NA") -> Optional[UUID]:
        """
        Change the DCS-X stepper location and set it as the X-axis pellet release location.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def set_dcs_y(self, value: float, *, absolute: bool = True, sender: str = "NA") -> Optional[UUID]:
        """
        Change the DCS-Y stepper location and set it as the Y-axis pellet release location.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def set_dcs_z(self, value: float, *, absolute: bool = True, sender: str = "NA") -> Optional[UUID]:
        """
        Change the DCS-Z stepper location and set it as the Z-axis pellet release location.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def move_x(self, value: float, *, absolute: bool = True) -> Optional[UUID]:
        """
        Move the X stepper.  This may not be supported on all device platforms.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def move_y(self, value: float, *, absolute: bool = True) -> Optional[UUID]:
        """
        Move the Y stepper.  This may not be supported on all device platforms.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def move_z(self, value: float, *, absolute: bool = True) -> Optional[UUID]:
        """
        Move the Z stepper.  This may not be supported on all device platforms.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def send_home(self) -> Optional[UUID]:
        """
        Request a move to 0, 0, 0.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def send_retract(self) -> Optional[UUID]:
        """Request a move to y - 10 (relative)
        :return: A token to expect from the device message handler when the request is complete.
        """

    def load_pellet(self) -> Optional[UUID]:
        """
        Request a full load cycle to scoop the pellet from the bin.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def send_pellet(self) -> Optional[UUID]:
        """
        Request a move from the current position to the "send" location stored in the hardware.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def cover_pellet(self) -> Optional[UUID]:
        """
        Request the barrier arm close and cover the pellet.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def release_pellet(self) -> Optional[UUID]:
        """
        Request the barrier arm open and expose the pellet.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def play_tone(self, frequency: int, duration: float) -> Optional[UUID]:
        """
        Request the device play a tone.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def set_motors_drift(self, drift: Offset3DTuple):
        """Set the motor drift offset"""

    def set_auto_correct_motor_drift(self, enabled: bool):
        """Set auto correct motor drift"""

    def set_tunnel_fan_on(self) -> Optional[UUID]:
        """Turn ON tunnel FAN"""

    def set_tunnel_fan_off(self) -> Optional[UUID]:
        """Turn OFF tunnel FAN"""



class TunnelHardwareProtocol(Protocol):
    @property
    def head_magnet_intensity(self) -> Optional[float]:
        """
        Return the current head magnet position.
        """

    def update_head_magnet_intensity(self, position: float) -> Optional[UUID]:
        """
        Request an update to the head magnet position.

        Args:
            position: The % position [0, 100] to set the head magnet.

        Returns:
            A token to expect from the device message handler when the request is complete.
        """

    def open_tunnel_gate(self) -> Optional[UUID]:
        """
        Request the tunnel gate to open.

        Returns:
            A token to expect from the device message handler when the request is complete.
        """

    def close_tunnel_gate(self) -> Optional[UUID]:
        """
        Request the tunnel gate to close.

        Returns:
            A token to expect from the device message handler when the request is complete.
        """

    def tare_load_cell(self) -> Optional[UUID]:
        """
        Request the load cell perform a tare operation.

        Returns:
            A token to expect from the device message handler when the request is complete.
        """
