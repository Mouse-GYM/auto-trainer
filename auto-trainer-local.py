import multiprocessing
import os
import sys
import argparse
import faulthandler
import logging


def main():

    from tools.acquisition.run_acquisition import run_acquisition

    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--configuration", help="configuration file", default=None, type=str)
    parser.add_argument("-d", "--dev", help="enable development mode and options", action="store_true")
    parser.add_argument("-e", "--allow-can-emulation", help="include CAN emulation as a connection option",
                        default="", type=str)

    args = parser.parse_args()

    # strtobool compatibility is all over the place.
    allow_emulation = args.allow_can_emulation.lower() in {"true", "yes", "1"}

    exit_val = run_acquisition(args.configuration, args.dev, allow_emulation)
    (logger.success if exit_val in (0, None) else logger.error)("acquisition finished ; exit_val=%s", exit_val)
    return exit_val


if __name__ == '__main__':
    faulthandler.enable()
    fork_method = "spawn"  # please check python multiprocessing fork method documentation
    multiprocessing.set_start_method(fork_method)  # MUST BE SET VERY EARLY BEFORE MOST IMPORTS
    # import autotrainer only AFTER having set mp start method,
    # otherwise it can be set by some other 3rd party dependency.
    from autotrainer.core.logging import setup_logging, stop_multiproc_logging, repr_all_loggers

    app_start_log_level = os.getenv("AUTOTRAINER_LOG_LEVEL", "NOTSET")
    if app_start_log_level.isdigit():
        app_start_log_level = int(app_start_log_level)

    # print(f"before:\n{repr_all_loggers()}")

    logger = setup_logging(
        "autotrainer",
        logger_level=app_start_log_level,
        time_precision=6,
        multiprocess_enabled=True,
        fork_method=fork_method,
    )

    # print(f"after:\n{repr_all_loggers()}")

    try:
        sys.exit(main())
    finally:
        stop_multiproc_logging()
