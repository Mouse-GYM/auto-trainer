import argparse
import logging
import sys


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("-e", "--allow-can-emulation", help="include CAN emulation as a connection option",
                        default="", type=str)

    args = parser.parse_args()

    # strtobool compatibility is all over the place.
    allow_emulation = args.allow_can_emulation.lower() in ["true", "yes", "1"]

    from tools.head_fix.run_head_fix_ui import run_head_fix_ui

    return run_head_fix_ui(allow_emulation)


if __name__ == '__main__':
    from autotrainer.core.logging import setup_logging
    setup_logging("autotrainer", logger_level=logging.DEBUG)
    sys.exit(main())
