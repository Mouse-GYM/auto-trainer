import pytest


pytest_plugins = [
    # NB: having to use another name than "fixtures(.py)" given otherwise it's overridden by:
    # ./auto-trainer-core/tests/fixtures
    # notably/already.
    "top_fixtures",
]


def pytest_addoption(parser):
    parser.addoption(
        "--functional", action="store_true", default=False, help="run functional tests"
    )
    parser.addoption(
        "--canbus", action="store_true", default=False, help="run canbus tests"
    )
    parser.addoption(
        "--run-bench", action="store_true", default=False, help="run bench tests"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "functional: mark test as functional")
    config.addinivalue_line("markers", "canbus: mark test as requiring canbus hardware")
    config.addinivalue_line("markers", "bench: mark test as performance/benchmark only")


def pytest_collection_modifyitems(config, items):
    include_functional = config.getoption("--functional")
    include_canbus = config.getoption("--canbus")
    include_bench = (
        "bench" in (config.getoption("-m") or "").split(" ")
        or config.getoption("--run-bench")
    )

    skip_functional = pytest.mark.skip(reason="need --functional option to run")
    skip_canbus = pytest.mark.skip(reason="need --canbus option to run")
    skip_bench = pytest.mark.skip(reason="need --run-bench option to run")

    for item in items:
        if "functional" in item.keywords and not include_functional:
            item.add_marker(skip_functional)
        if "canbus" in item.keywords and not include_canbus:
            item.add_marker(skip_canbus)
        if "bench" in item.keywords and not include_bench:
            item.add_marker(skip_bench)
