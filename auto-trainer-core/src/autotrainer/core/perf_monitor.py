import logging
import time
from dataclasses import dataclass, field
from math import floor

logger = logging.getLogger(__name__)


@dataclass()
class PerfMonitor:
    name: str = ""
    units: str = ""
    report_count: int = 30
    enable_log: bool = True
    log_level: int = logging.DEBUG
    cps: float = 0.0

    _cycle_count: int = field(default=0, init=False, repr=False, compare=False)
    _start: int = field(default=0, init=False, repr=False, compare=False)

    def reset(self):
        self._cycle_count = 0

    def add_cycle(self) -> bool:
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
