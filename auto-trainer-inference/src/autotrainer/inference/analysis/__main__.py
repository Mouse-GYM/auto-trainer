import argparse
import logging
import sys
from pathlib import Path
from pprint import pprint
from datetime import datetime, date

import verboselogs

from autotrainer.core import get_verbose_logger, ProjectInfo
from autotrainer.core.logging import setup_logging

from autotrainer.inference.analysis import intersession_process

logger = get_verbose_logger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("unit")
    parser.add_argument("date", type=lambda v: datetime.strptime(v, "%Y%m%d"))
    parser.add_argument("session", type=int)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--calib-dir", type=Path, required=True)
    args = parser.parse_args()
    # and then execute:
    project_info = ProjectInfo(
        root=args.data_dir,
        device_id=args.unit,
        when=args.date,
        session=args.session,
    )
    print(project_info.get_session_path())
    result = intersession_process(project_info, calib_dir=args.calib_dir)
    pprint(result)


if __name__ == "__main__":
    setup_logging("autotrainer", logger_level=logging.DEBUG)
    sys.exit(main())
