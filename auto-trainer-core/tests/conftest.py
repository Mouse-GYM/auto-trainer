
import pytest

from autotrainer.core import EventManager


@pytest.fixture(autouse=True)
def _auto_close_event_manager():
    # allow to close the EventManager and have its worker thread exits gracefully (on each end of test case)
    yield
    mgr = getattr(EventManager, "_instance", None)
    if mgr is not None:
        assert isinstance(mgr, EventManager)
        mgr.close()
        del EventManager._instance  # noqa
