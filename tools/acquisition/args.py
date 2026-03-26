
import argparse
from pathlib import Path

from tools.acquisition.model.app_model_status import AppModelStatus


def parse_start_mode(value: str):
    # from tools.acquisition.model.app_model_status import AppModelStatus
    try:
        return AppModelStatus(value.lower())  # values are lower, so force it
    except ValueError:
        pass
    try:
        return getattr(AppModelStatus, value.upper())  # names are upper, so force it
    except AttributeError:
        pass
    raise ValueError(f"Unknown AppModelStatus: {value!r}")


def make_autotrainer_parser(*, allow_dev_mode: bool=False):
    parser = argparse.ArgumentParser(
        prog="Autotrainer",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-c", "--configuration", help="configuration file", default=None, type=Path)
    parser.add_argument("--preferences-file", help="user preference ini file", default=None, type=Path)
    parser.add_argument("--start-mode", help="The desired start system mode",
                        choices=list(v.value for v in AppModelStatus), type=parse_start_mode,
                        default=AppModelStatus.ACQUIRING)
    if allow_dev_mode:
        parser.add_argument("-d", "--dev", help="enable development mode and options", action="store_true")
        parser.add_argument("-e", "--allow-can-emulation", help="include CAN emulation as a connection option",
                            default="", type=str)
    return parser
