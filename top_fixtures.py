import logging
import time
from pathlib import Path
from unittest import mock

import pytest
import sys

from autotrainer.core import EventManager, ProjectInfo

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


@pytest.fixture
def project_info(tmp_path):
    root = tmp_path.joinpath("root")
    root.mkdir()
    prj = ProjectInfo(root=root.as_posix())
    yield prj


@pytest.fixture
def m_time_time():
    """Allow to control time.time()"""
    with mock.patch.object(time, "time") as m_time:
        yield m_time


