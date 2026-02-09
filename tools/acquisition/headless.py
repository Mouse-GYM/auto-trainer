import logging
import os
import time
import sys
import argparse
import faulthandler
from pathlib import Path
from multiprocessing import set_start_method


def _exec_main():

    from autotrainer.core.logging import get_verbose_logger

    from tools.acquisition.model.user_preferences import UserPreferences
    from tools.acquisition.model.app_model import AppModel

    logger = get_verbose_logger("autotrainer.headless")

    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--configuration", help="configuration file", default=None, type=Path)
    parser.add_argument("--preferences-file", help="user preference ini file", default=None, type=Path)

    args = parser.parse_args()
    configuration = args.configuration

    if configuration and not os.path.exists(configuration):
        return -1

    preferences = UserPreferences(settings_file_path=args.preferences_file)

    get_console_handler().setLevel(preferences.log_level)

    app_view_model = AppModel(preferences)

    try:
        app_view_model.load_configuration(configuration)
    except Exception as err:
        logger.exception("Could not load config: %s", err)
        app_view_model.on_close()
        return 1

    app_view_model.on_activated()

    if not app_view_model.on_capture_start():
        logger.error("failed to start capture")
        return 1

    logger.success("App is now running")

    exit_rc = 1
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Interrupted, exiting..")
        exit_rc = 0
    except Exception as err:
        logger.exception("Fatal error: %s", err)

    app_view_model.on_close()

    return exit_rc


def main():
    faulthandler.enable()
    set_start_method("spawn")

    # must be AFTER set_start_method below:
    from autotrainer.core.logging import setup_logging, get_console_handler, stop_multiproc_logging

    logger = setup_logging(logger_level=logging.DEBUG, time_precision=6, multiprocess_enabled=True)

    try:
        return _exec_main()
    except KeyboardInterrupt:
        logger.notice("KeyboardInterrupt")
        exit_code = 0
    except Exception as err:
        logger.exception("Fatal error: %s", err)
        exit_code = 1
    finally:
        from autotrainer.core.event import EventManager
        from autotrainer.behavior import BehaviorAlgorithm
        BehaviorAlgorithm.close_algorithm_handler()
        EventManager.try_close_default()
        stop_multiproc_logging()
    #
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
