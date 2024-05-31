import logging
import sys
from multiprocessing import set_start_method

from tools.acquisition.run_acquisition import run_acquisition

logging.basicConfig(level=logging.WARNING)
logging.getLogger('tools').setLevel(logging.DEBUG)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)

if __name__ == '__main__':
    set_start_method("spawn")

    if run_acquisition():
        sys.exit(0)
    else:
        sys.exit(1)
