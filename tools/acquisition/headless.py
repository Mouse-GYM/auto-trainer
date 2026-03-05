import logging
import os
import time
import sys
import argparse
import faulthandler
from pathlib import Path
from multiprocessing import set_start_method

from autotrainer.core import PersistenceConfiguration


# NB: do not put any imports of autotrainer* or any module not part from standard python lib.


def _exec_main(args):

    from autotrainer.core.logging import get_verbose_logger, get_console_handler, set_log_location
    from autotrainer.core.project import ProjectInfo

    from tools.acquisition.model.user_preferences import UserPreferences
    from tools.acquisition.model.app_model import AppModel

    logger = get_verbose_logger("autotrainer.headless")

    configuration = args.configuration
    if configuration and not os.path.exists(configuration):
        return -1

    preferences = UserPreferences(settings_file_path=args.preferences_file)

    get_console_handler().setLevel(preferences.log_level)

    app_model = AppModel(preferences)

    try:
        app_model.load_configuration(configuration)
    except Exception as err:
        logger.exception("Could not load config: %s", err)
        app_model.on_close()
        return 1

    if not app_model.capture_start():
        logger.error("failed to start capture")
        app_model.on_close()
        return 1

    logger.success("App is now running")

    app_model.on_activated()

    exit_rc = 1
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Interrupted, exiting..")
        exit_rc = 0
    except Exception as err:
        logger.exception("Fatal error: %s", err)

    app_model.on_close()

    return exit_rc


def main():
    faulthandler.enable()
    set_start_method("spawn")

    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--configuration", help="configuration file", default=None, type=Path)
    parser.add_argument("--preferences-file", help="user preference ini file", default=None, type=Path)

    args = parser.parse_args()

    # must be AFTER set_start_method below:
    from autotrainer.core.logging import setup_logging, get_console_handler, stop_multiproc_logging

    logger = setup_logging(logger_level=logging.DEBUG, time_precision=6, multiprocess_enabled=True)

    try:
        return _exec_main(args)
    except KeyboardInterrupt:
        logger.notice("KeyboardInterrupt")
        exit_code = 0
    except Exception as err:
        logger.exception("Fatal error: %s", err)
        exit_code = 1
    finally:
        from autotrainer.core.event.event_manager import EventManager
        from autotrainer.behavior import BehaviorAlgorithm
        BehaviorAlgorithm.close_algorithm_handler()
        EventManager.try_close_default()
        stop_multiproc_logging()
    #
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
