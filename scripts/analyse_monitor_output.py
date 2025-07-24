
import argparse
import sys
from collections import deque
from pathlib import Path
from typing import TextIO
from unittest import mock

import autotrainer.core.logging
from autotrainer.core import LoadCellMonitor
from autotrainer.core.analysis import LoadCellConfiguration



def process_path(
    fh: TextIO,
    *,
    warn_diff_threshold: float,
    only_with_begin_end_marks: bool = False,
):
    prev = None
    fh.readline()  # drop header
    cfg = LoadCellConfiguration()
    monitor = LoadCellMonitor(config=cfg)

    prev_ts_changed = {}
    props = {}
    m_timer = mock.patch(f"{LoadCellMonitor.__module__}._timer_load_cell_engaged")
    m_timer.start()  # this disables the "interactive/live" "timeout" timers
    t0 = None

    def handle_prop_changed(name, new_value, prev_value):
        nonlocal prev_ts_changed
        prop_prev = props.get(name, None)
        if prop_prev is None or prop_prev != new_value:
            prev_changed = prev_ts_changed.get(name, None)
            if prev_changed is None:
                prev_changed = ts
            if name != "is_thrashing_detected" or new_value:
                print(f"T={ts - t0:.2f} {name}: {prev_value} -> {ts - prev_changed:.2f}s -> {new_value} ; w={weight:.1f}")
            # print(ts, ts - prev_ts_changed, name, new_value, weight)
            prev_ts_changed[name] = ts
        props[name] = new_value

    monitor.property_changed += handle_prop_changed

    capturing = not only_with_begin_end_marks

    while True:
        line = fh.readline()
        if not line:
            break
        line = line.strip()
        if line.startswith("#"):
            if only_with_begin_end_marks:
                if "BEGIN" in line:
                    capturing = True
                    print(line)
                elif "END" in line:
                    capturing = False
                    print(line)
            continue
        if not capturing:
            t0 = None
            continue
        parts = [p.strip() for p in line.split(",")]
        ts = float(parts[0])
        if t0 is None:
            t0 = ts
        idx = int(parts[1])
        weight = float(parts[2])
        monitor.update(weight, ts, idx)
        if prev is not None:
            diff = ts - prev
            if ts - prev > warn_diff_threshold:
                print(f"diff={diff:.3f} ts={ts} ; prev={prev}")
        prev = ts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path", type=Path)
    parser.add_argument("--warn_diff_threshold", type=float, default=0.1)
    parser.add_argument("--only_with_begin_end_marks", action="store_true", default=False,
                        help="Only process values between # BEGIN and # END comment lines")

    args = parser.parse_args()

    path: Path = args.input_path
    print(f"Processing {path}")
    with path.open() as fh:
        process_path(fh,
                     warn_diff_threshold=args.warn_diff_threshold,
                     only_with_begin_end_marks=args.only_with_begin_end_marks)

    print("finished")


if __name__ == "__main__":
    autotrainer.core.logging.setup_logging()
    main()
