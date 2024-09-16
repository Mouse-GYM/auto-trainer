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
    log_level: int = logging.DEBUG

    _cycle_count: int = field(default=0, init=False, repr=False, compare=False)
    _start: int = field(default=0, init=False, repr=False, compare=False)

    def reset(self):
        self._cycle_count = 0

    def add_cycle(self):
        if self._cycle_count == 0:
            self._start = time.perf_counter_ns()

        self._cycle_count += 1

        if self._cycle_count % self.report_count == 0:
            cps = 1e9 * self._cycle_count / (time.perf_counter_ns() - self._start)
            logger.log(self.log_level, f"{self.name}: {cps:.1f} {self.units}")

    def add_cycles(self, cycles: int):
        if cycles <= 0:
            return

        if self._cycle_count == 0:
            self._start = time.perf_counter_ns()

        major = floor(self._cycle_count / self.report_count)

        self._cycle_count += cycles

        if self._cycle_count % self.report_count == 0 or floor(self._cycle_count / self.report_count) > major:
            cps = 1e9 * self._cycle_count / (time.perf_counter_ns() - self._start)
            logger.log(self.log_level, f"{self.name}: {cps:.1f} {self.units}")
