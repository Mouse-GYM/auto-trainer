import logging
from pathlib import Path

import pytest
import sys

from autotrainer.core import EventManager


logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def auto_close_event_manager():
    # allow to close the EventManager and have its worker thread exits gracefully (on each end of test case)
    yield
    mgr = getattr(EventManager, "_instance", None)
    if mgr is not None:
        assert isinstance(mgr, EventManager)
        mgr.close()
        del EventManager._instance  # noqa


@pytest.fixture(autouse=True, scope="session")
def auto_set_misc_log_level():
    # some logger we don't want too verbose in any case
    logging.getLogger('transitions').setLevel(logging.INFO)
