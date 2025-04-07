import logging
import os

import time

logging.basicConfig(level=logging.WARNING, format="%(asctime)s: %(levelname)s: %(name)s: %(message)s")
logging.getLogger("transitions").setLevel(logging.WARNING)
logging.getLogger("autotrainer").setLevel(logging.WARNING)
logging.getLogger("tools").setLevel(logging.WARNING)
logging.getLogger("inference_algorithms").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def update_log_level(value: int):
    logging.getLogger("inference_algorithms").setLevel(value)
    logging.getLogger("tools").setLevel(value)
    logging.getLogger("autotrainer").setLevel(value)

    if value == logging.DEBUG:
        logging.getLogger("transitions").setLevel(logging.INFO)
    else:
        logging.getLogger("transitions").setLevel(logging.WARNING)


def main(configuration: str):
    from tools.acquisition.model.user_preferences import UserPreferences
    from tools.acquisition.model.app_model import AppModel

    if configuration and not os.path.exists(configuration):
        return -1

    preferences = UserPreferences()

    update_log_level(preferences.log_level)

    app_view_model = AppModel(preferences)

    if app_view_model.load_configuration(configuration or preferences.last_configuration):
        if configuration:
            preferences.last_configuration = configuration

    app_view_model.head_fix.on_activated()
    app_view_model._pellet_delivery.on_activated()

    if not app_view_model.on_capture_start():
        logger.error("failed to start capture")
        return -1

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        app_view_model.on_capture_stop()
        return 0


if __name__ == '__main__':
    import sys
    import argparse
    import faulthandler
    from multiprocessing import set_start_method

    faulthandler.enable()

    set_start_method("spawn")

    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--configuration", help="configuration file", default=None, type=str)

    args = parser.parse_args()

    if main(args.configuration):
        sys.exit(0)
    else:
        sys.exit(1)
