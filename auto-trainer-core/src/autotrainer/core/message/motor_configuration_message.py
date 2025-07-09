from typing import Protocol, Tuple
from enum import IntEnum

"""
Identifiers for the different motor types
"""


class Motor(IntEnum):
    NONE = 0
    TUNNEL_MAGNET_SERVO = 1
    PELLET_X_MOTOR = 2
    PELLET_Y_MOTOR = 3
    PELLET_Z_MOTOR = 4
    PELLET_COVER_SERVO = 5
    PELLET_LOAD_SERVO = 6
    TUNNEL_GATE_SERVO = 7


"""
Protocol for the interface for obtaining stepper motor configuration entities
"""


class StepperConfigMessage(Protocol):
    """
    Motor associated with the configuration
    """

    @property
    def motor(self) -> Motor: ...

    """
    Units: turns/sec
    """

    @property
    def maximum_velocity(self) -> float: ...

    """
    Units: turns/sec^2
    """

    @property
    def maximum_acceleration(self) -> float: ...

    """
    Units: 1/min step
    """

    @property
    def minimum_step_inverted(self) -> int: ...

    """
    Units: steps/rev
    """

    @property
    def steps_per_revolution(self) -> float: ...

    """
    0 - Do no invert motor direction
    1 - Invert motor direction
    """

    @property
    def flip_limit_orientation(selfs) -> int: ...


"""
Protocol for the interface for obtaining servo motor configuration entities
"""


class ServoConfigMessage(Protocol):
    """
    Motor associated with the configuration
    """

    @property
    def motor(self) -> Motor: ...

    """
    Units: deg/sec
    """

    @property
    def maximum_velocity(self) -> float: ...

    """
    Units: deg/sec^2
    """

    @property
    def maximum_acceleration(self) -> float: ...

    """
    Units: deg
    """

    @property
    def minimum_position(self) -> float: ...

    """
    Units: deg
    """

    @property
    def maximum_position(self) -> float: ...

    """
    Units: µs
    """

    @property
    def min_pwm_duration(self) -> float: ...

    """
    Units: µs
    """

    @property
    def max_pwm_duration(self) -> float: ...


"""
Protocol for access to a full set of motor configurations
"""


class MotorConfigurations(Protocol):

    @property
    def magnet_config(self) -> Tuple[Motor, ServoConfigMessage]: ...

    @property
    def gate_config(self) -> Tuple[Motor, ServoConfigMessage]: ...

    @property
    def load_config(self) -> Tuple[Motor, ServoConfigMessage]: ...

    @property
    def cover_config(self) -> Tuple[Motor, ServoConfigMessage]: ...

    @property
    def x_config(self) -> Tuple[Motor, StepperConfigMessage]: ...

    @property
    def y_config(self) -> Tuple[Motor, StepperConfigMessage]: ...

    @property
    def z_config(self) -> Tuple[Motor, StepperConfigMessage]: ...
