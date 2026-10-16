from typing import Protocol


class MeasurementMessageProtocol(Protocol):
    """
    MeasurementMessage defines the expected interface for measurement data provided by the hardware.  This is expected
    object passed as part of a SystemStatusMessageKind.MEASUREMENTS message.
    """

    @property
    def when(self) -> float:
        """Value of time.time() or equivalent absolute time provided by the hardware."""

    # Deprecated
    @property
    def timestamp(self) -> int:
        """
        A relative time index in nanoseconds. Provides finer resolution between measurements than absolute time may
        provide on some platforms.  By default, would be provided by time.perf_counter_ns().
        """

    @property
    def index(self) -> int:
        """
        A relative time index in nanoseconds. Provides finer resolution between measurements than absolute time may
        provide on some platforms.  By default, would be provided by time.perf_counter_ns().
        """

    @property
    def weight(self) -> float:
        """The load cell value in grams."""

    @property
    def pressure(self) -> float:
        """The force detector value in the range of [0, 1024]"""

    # Deprecated
    @property
    def switch(self) -> float:
        """The head contact DIO value as 0 or 1."""

    @property
    def temperature(self) -> float:
        """The temperature in Celsius."""

    @property
    def humidity(self) -> float:
        """The relative humidity (%)."""

    @property
    def head_contact(self) -> bool:
        """The head contact DIO value state.  True if contact is made, False otherwise."""
