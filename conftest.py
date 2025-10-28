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
    def has_option(mark_name, with_no_run: bool = False):
        return (
            mark_name in (config.getoption("-m") or "").split(" ")
            or config.getoption(f"--{mark_name}" if with_no_run else f"--run-{mark_name}")
        )
    include_functional = has_option("functional", with_no_run=True)
    include_canbus = has_option("canbus", with_no_run=True)
    include_bench = has_option("bench")

    skip_functional = pytest.mark.skip(reason="need --functional option to run")
    skip_canbus = pytest.mark.skip(reason="need --canbus option to run")
    skip_bench = pytest.mark.skip(reason="need --run-bench option or -m bench to run")

    for item in items:
        if "functional" in item.keywords and not include_functional:
            item.add_marker(skip_functional)
        if "canbus" in item.keywords and not include_canbus:
            item.add_marker(skip_canbus)
        if "bench" in item.keywords and not include_bench:
            item.add_marker(skip_bench)
