import multiprocessing
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
    sys.exit(exit_val)


if __name__ == '__main__':
    faulthandler.enable()
    multiprocessing.set_start_method("spawn")  # MUST BE SET VERY EARLY BEFORE MOST IMPORTS
    # import autotrainer only AFTER having set mp start method,
    # otherwise it can be set by some other 3rd party dependency.
    from autotrainer.core.logging import setup_logging
    logger = setup_logging("autotrainer", logger_level=logging.DEBUG, time_precision=6)
    sys.exit(main())
