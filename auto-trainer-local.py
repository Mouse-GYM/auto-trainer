import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s: %(levelname)s: %(name)s: %(message)s")

cur_desired_lvl = logging.WARNING

logging.getLogger("transitions").setLevel(cur_desired_lvl)
logging.getLogger("tools").setLevel(cur_desired_lvl)
logging.getLogger("autotrainer").setLevel(cur_desired_lvl)
logging.getLogger("inference_algorithms").setLevel(cur_desired_lvl)


if __name__ == '__main__':
    import sys
    import argparse
    import faulthandler
    from multiprocessing import set_start_method
    from tools.acquisition.run_acquisition import run_acquisition

    faulthandler.enable()

    set_start_method("spawn")

    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--configuration", help="configuration file", default=None, type=str)
    parser.add_argument("-d", "--dev", help="enable development mode and options", action="store_true")
    parser.add_argument("-e", "--allow-can-emulation", help="include CAN emulation as a connection option",
                        default="", type=str)

    args = parser.parse_args()

    # strtobool compatibility is all over the place.
    allow_emulation = args.allow_can_emulation.lower() in ["true", "yes", "1"]

    if run_acquisition(args.configuration, args.dev, allow_emulation):
        sys.exit(0)
    else:
        sys.exit(1)
