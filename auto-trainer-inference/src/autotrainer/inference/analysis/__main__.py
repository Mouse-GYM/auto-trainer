import argparse
import logging
import sys
from pathlib import Path
from pprint import pprint
from datetime import datetime, date

import verboselogs

from autotrainer.core import get_verbose_logger, ProjectInfo
from autotrainer.core.logging import setup_logging, get_console_handler

from autotrainer.inference.analysis import intersession_process

logger = get_verbose_logger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("unit")
    parser.add_argument("date", type=lambda v: datetime.strptime(v, "%Y%m%d"))
    parser.add_argument("session", type=int)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--calib-dir", type=Path, required=True)
    parser.add_argument("--log-level", type=lambda val: int(val) if val.isdigit() else val,
                        default=logging.WARNING)
    parser.add_argument("--analysis-debug-level", type=int, help="integer", default=0)
    args = parser.parse_args()
    logging.root.setLevel(args.log_level)
    get_console_handler().setLevel(args.log_level)
    # and then execute:
    project_info = ProjectInfo(
        root=args.data_dir,
        device_id=args.unit,
        when=args.date,
        session=args.session,
    )
    result = intersession_process(
        project_info,
        calib_dir=args.calib_dir,
        debug_level=args.analysis_debug_level,
    )
    print(f"{project_info.get_session_path()}: {result}")
    # pprint(result)


if __name__ == "__main__":
    setup_logging("autotrainer")
    sys.exit(main())
