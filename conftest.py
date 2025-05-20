import pytest

from autotrainer.core import EventManager


# not sure why yet but not working, have to put it in each conftest of each auto-trainer component
# @pytest.fixture(autouse=True)
# def _event_manager():
#     # allow to close the EventManager and have its worker thread exits gracefully (on each end of test case)
#     yield
#     mgr = EventManager.default()
#     mgr.close()
#     del EventManager._instance  # noqa


def pytest_addoption(parser):
    parser.addoption(
        "--functional", action="store_true", default=False, help="run functional tests"
    )
    parser.addoption(
        "--canbus", action="store_true", default=False, help="run canbus tests"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "functional: mark test as functional")
    config.addinivalue_line("markers", "canbus: mark test as requiring canbus hardware")


def pytest_collection_modifyitems(config, items):
    include_functional = config.getoption("--functional")
    include_canbus = config.getoption("--canbus")

    skip_functional = pytest.mark.skip(reason="need --functional option to run")
    skip_canbus = pytest.mark.skip(reason="need --canbus option to run")

    for item in items:
        if "functional" in item.keywords and not include_functional:
            item.add_marker(skip_functional)
        if "canbus" in item.keywords and not include_canbus:
            item.add_marker(skip_canbus)
