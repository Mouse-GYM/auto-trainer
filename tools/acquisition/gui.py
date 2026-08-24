import multiprocessing
import os
import sys
import faulthandler

# NB: do not put any imports of autotrainer* or any module not part from standard python lib.

def _exec_main(args, logger):

    from tools.acquisition.run_acquisition import run_acquisition

    exit_val = run_acquisition(args)
    (logger.success if exit_val in (0, None) else logger.error)("application finished ; exit_val=%s", exit_val)
    return exit_val


def main():
    faulthandler.enable()
    fork_method = "spawn"  # please check python multiprocessing fork method documentation
    multiprocessing.set_start_method(fork_method)  # MUST BE SET VERY EARLY BEFORE MOST IMPORTS

    from tools.acquisition.args import parse_autotrainer_args

    args = parse_autotrainer_args(allow_dev_mode=True)

    # import autotrainer only AFTER having set mp start method,
    # otherwise it can be set by some other 3rd party dependency.
    from autotrainer.core.logging import setup_logging, stop_multiproc_logging

    app_start_log_level = os.getenv("AUTOTRAINER_LOG_LEVEL", "NOTSET")
    if app_start_log_level.isdigit():
        app_start_log_level = int(app_start_log_level)

    logger = setup_logging(
        "autotrainer",
        logger_level=app_start_log_level,
        time_precision=6,
        multiprocess_enabled=True,
        fork_method=fork_method,
    )

    try:
        return _exec_main(args, logger)
    except Exception as err:
        logger.exception("Fatal error: %s", err)
        return 1
    finally:
        stop_multiproc_logging()


if __name__ == '__main__':
    sys.exit(main())
