import logging
import sys

from autotrainer.dlc.dlc_configuration import DLCConfiguration

logging.getLogger("autotrainer").setLevel(logging.DEBUG)

for idx in range(1, len(sys.argv)):
    configuration = DLCConfiguration()

    configuration.load_configuration(sys.argv[idx])

    print(f"=== Network {sys.argv[idx]} ===")
    print(f"Body Part Categories:\t{configuration.body_part_categories}")
    print(f"Body Parts:\t\t\t\t{configuration.body_parts}")
