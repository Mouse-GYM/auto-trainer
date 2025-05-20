
import pytest

from autotrainer.core import EventManager


@pytest.fixture(autouse=True)
def _event_manager():
    # allow to close the EventManager and have its worker thread exits gracefully (on each end of test case)
    yield
    mgr = EventManager.default()
    mgr.close()
    del EventManager._instance  # noqa
