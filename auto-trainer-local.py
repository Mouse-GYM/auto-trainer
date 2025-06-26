import logging
import multiprocessing
import sys
import argparse
import faulthandler


if __name__ == '__main__':

    faulthandler.enable()

    multiprocessing.set_start_method("spawn")  # MUST BE SET VERY EARLY BEFORE MOST IMPORTS

    from autotrainer.core.logging import setup_logging

    setup_logging()

    cur_desired_lvl = logging.WARNING

    logging.getLogger("transitions").setLevel(cur_desired_lvl)
    logging.getLogger("tools").setLevel(cur_desired_lvl)
    logging.getLogger("autotrainer").setLevel(cur_desired_lvl)
    logging.getLogger("inference_algorithms").setLevel(cur_desired_lvl)

    from tools.acquisition.run_acquisition import run_acquisition

    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--configuration", help="configuration file", default=None, type=str)
    parser.add_argument("-d", "--dev", help="enable development mode and options", action="store_true")
    parser.add_argument("-e", "--allow-can-emulation", help="include CAN emulation as a connection option",
                        default="", type=str)
    parser.add_argument("--simulate-trigger-load-cell", action="store_true")

    args = parser.parse_args()

    # strtobool compatibility is all over the place.
    allow_emulation = args.allow_can_emulation.lower() in {"true", "yes", "1"}

    sys.exit(run_acquisition(args.configuration, args.dev, allow_emulation,
                             simulate_trigger_load_cell=args.simulate_trigger_load_cell))
