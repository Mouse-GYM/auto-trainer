import logging
import sys

from tools.head_fix.run_head_fix_ui import run_head_fix_ui

logging.basicConfig(level=logging.WARNING)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logging.getLogger('tools').setLevel(logging.DEBUG)

if __name__ == '__main__':
    if run_head_fix_ui():
        sys.exit(0)
    else:
        sys.exit(1)
