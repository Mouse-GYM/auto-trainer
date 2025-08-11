import argparse
import sys

import verboselogs

from autotrainer.behavior import intersession_process
from autotrainer.core import get_verbose_logger, ProjectInfo
from autotrainer.core.logging import setup_logging

logger = get_verbose_logger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument()
    # TODO: add arguments to allow pass needed args to reconstitute an ProjectInfo full instance,
    args = parser.parse_args()
    # and then execute:
    project_info = ProjectInfo(**vars(args))  # smth like that
    result = intersession_process(project_info)
    print(f"{project_info.get_session_path()} => {result}")


if __name__ == "__main__":
    setup_logging("autotrainer", logger_level=verboselogs.VERBOSE)
    sys.exit(main())
