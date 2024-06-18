import logging

logging.basicConfig(level=logging.WARNING)
logging.getLogger("tools").setLevel(logging.DEBUG)
logging.getLogger("autotrainer").setLevel(logging.DEBUG)

if __name__ == '__main__':
    import sys
    import argparse
    from multiprocessing import set_start_method
    from tools.acquisition.run_acquisition import run_acquisition

    set_start_method("spawn")

    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--configuration", help="configuration file", default=None, type=str)

    args = parser.parse_args()

    if run_acquisition(args.configuration):
        sys.exit(0)
    else:
        sys.exit(1)
