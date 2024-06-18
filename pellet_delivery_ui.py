import logging
import sys

from tools.pellet_delivery.run_pellet_delivery_ui import run_pellet_delivery_ui

logging.basicConfig(level=logging.WARNING)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logging.getLogger('tools').setLevel(logging.DEBUG)

if __name__ == '__main__':
    if run_pellet_delivery_ui():
        sys.exit(0)
    else:
        sys.exit(1)
