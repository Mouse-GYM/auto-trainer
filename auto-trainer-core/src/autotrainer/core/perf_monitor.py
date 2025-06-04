import logging
import time
from dataclasses import dataclass, field
from math import floor

logger = logging.getLogger(__name__)


@dataclass
class PerfMonitor:
    """
    Convenience class to measure and report performance metrics.  There are likely more robust or feature complete
    packages available.  This is intended as a simple implementation to not add to the dependency list of the project.

    The monitor tracks `cycles` or number of times something happens.  What this means is defined by the caller.
    """
    name: str = ""
    """User-friendly name for the performance monitor."""
    units: str = ""
    """Units for the performance monitor."""
    report_count: int = 30
    """Number of `cycles` for displaying performance metrics.  This is used to reduce the number of log messages."""
    enable_log: bool = True
    """Allow toggling reporting while running."""
    log_level: int = logging.DEBUG
    """Log level for reporting performance metrics."""
    cps: float = 0.0
    """Most recent cycles per second (CPS) value."""

    _cycle_count: int = field(default=0, init=False, repr=False, compare=False)
    _start: int = field(default=0, init=False, repr=False, compare=False)

    def reset(self):
        """
        Resets all cycle counts and timing.  Calculations will resume on the next `add_cycle` or `add_cycles` call.
        """
        self._cycle_count = 0

    def add_cycle(self) -> bool:
        """
        Add a single cycle to the count.

        Returns:
            bool: True if the cycle count is a multiple of `report_count` and the CPS value was/would be reported.
        """
        if self._cycle_count == 0:
            self._start = time.perf_counter_ns()

        self._cycle_count += 1

        if self._cycle_count % self.report_count == 0:
            self.cps = 1e9 * self._cycle_count / (time.perf_counter_ns() - self._start)
            if self.enable_log:
                logger.log(self.log_level, f"{self.name}: {self.cps:.1f} {self.units}")
            return True

        return False

    def add_cycles(self, cycles: int) -> bool:
        """
        Add a block of cycles to the count.

        Returns:
            bool: True if the cycle count passed a multiple of `report_count` and the CPS value was/would be reported.
        """
        if cycles <= 0:
            return False

        if self._cycle_count == 0:
            self._start = time.perf_counter_ns()

        major = floor(self._cycle_count / self.report_count)

        self._cycle_count += cycles

        if self._cycle_count % self.report_count == 0 or floor(self._cycle_count / self.report_count) > major:
            self.cps = 1e9 * self._cycle_count / (time.perf_counter_ns() - self._start)
            if self.enable_log:
                logger.log(self.log_level, f"{self.name}: {self.cps:.1f} {self.units}")
            return True

        return False
