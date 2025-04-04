import argparse
import logging
import sys

from tools.pellet_delivery.run_pellet_delivery_ui import run_pellet_delivery_ui

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s\t [%(name)s] %(message)s")
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logging.getLogger('tools').setLevel(logging.DEBUG)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("-e", "--allow-can-emulation", help="include CAN emulation as a connection option",
                        default="", type=str)

    args = parser.parse_args()

    # strtobool compatibility is all over the place.
    allow_emulation = args.allow_can_emulation.lower() in ["true", "yes", "1"]

    if run_pellet_delivery_ui(allow_emulation):
        sys.exit(0)
    else:
        sys.exit(1)
