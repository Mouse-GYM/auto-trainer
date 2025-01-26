import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--functional", action="store_true", default=False, help="run functional tests"
    )
    parser.addoption(
        "--whisker", action="store_true", default=False, help="run whisker tests"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "functional: mark test as functional")
    config.addinivalue_line("markers", "whisker: mark test as requiring whisker hardware")


def pytest_collection_modifyitems(config, items):
    include_functional = config.getoption("--functional")
    include_whisker = config.getoption("--whisker")

    skip_functional = pytest.mark.skip(reason="need --functional option to run")
    skip_whisker = pytest.mark.skip(reason="need --whisker option to run")

    for item in items:
        if "functional" in item.keywords and not include_functional:
            item.add_marker(skip_functional)
        if "whisker" in item.keywords and not include_whisker:
            item.add_marker(skip_whisker)
