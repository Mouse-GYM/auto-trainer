import subprocess
import sys

import pytest

import autotrainer.core
from autotrainer.core import package_version


SOURCE_NAMES = ("_version_from_checkout", "_version_from_file", "_version_from_metadata")


@pytest.fixture(autouse=True)
def _clear_version_cache():
    package_version.get_version.cache_clear()
    try:
        yield
    finally:
        package_version.get_version.cache_clear()


def _fail_if_called(*args, **kwargs):
    pytest.fail(f"unexpected subprocess call: {args} {kwargs}")


def _make_source_layout(project_dir):
    package_dir = project_dir.joinpath("src", "autotrainer", "core")
    package_dir.mkdir(parents=True)
    project_dir.joinpath("pyproject.toml").write_text("")
    return package_dir


@pytest.mark.parametrize("first_found", range(len(SOURCE_NAMES)))
def test_first_source_with_a_version_wins(monkeypatch, first_found):
    for idx, name in enumerate(SOURCE_NAMES):
        version = None if idx < first_found else f"{idx}.0.0"
        monkeypatch.setattr(package_version, name, lambda version=version: version)
    assert package_version.get_version() == f"{first_found}.0.0"


def test_placeholder_when_no_source_has_a_version(monkeypatch):
    for name in SOURCE_NAMES:
        monkeypatch.setattr(package_version, name, lambda: None)
    assert package_version.get_version() == package_version.PLACEHOLDER_VERSION == "0.0.0"


def test_installed_layout_skips_git(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "check_output", _fail_if_called)
    package_dir = tmp_path.joinpath("site-packages", "autotrainer", "core")
    assert package_version._version_from_checkout(package_dir) is None


def test_source_layout_without_git_skips_git(monkeypatch, tmp_path):
    if any(directory.joinpath(".git").exists() for directory in tmp_path.parents):
        pytest.skip("tmp_path is inside a git checkout")
    monkeypatch.setattr(subprocess, "check_output", _fail_if_called)
    package_dir = _make_source_layout(tmp_path.joinpath("proj"))
    assert package_version._version_from_checkout(package_dir) is None


def test_source_layout_with_git_asks_setuptools_scm(monkeypatch, tmp_path):
    project_dir = tmp_path.joinpath("proj")
    package_dir = _make_source_layout(project_dir)
    project_dir.joinpath(".git").mkdir()
    calls = []

    def fake_check_output(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return b"3.1.4\n"

    monkeypatch.setattr(package_version, "_has_setuptools_scm", lambda: True)
    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    assert package_version._version_from_checkout(package_dir) == "3.1.4"
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd == [sys.executable, "-m", "setuptools_scm"]
    assert kwargs["cwd"] == project_dir


def test_source_layout_with_failing_setuptools_scm(monkeypatch, tmp_path):
    project_dir = tmp_path.joinpath("proj")
    package_dir = _make_source_layout(project_dir)
    project_dir.joinpath(".git").mkdir()

    def failing_check_output(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(package_version, "_has_setuptools_scm", lambda: True)
    monkeypatch.setattr(subprocess, "check_output", failing_check_output)
    assert package_version._version_from_checkout(package_dir) is None


def test_module_attribute(monkeypatch):
    monkeypatch.setattr(package_version, "_version_from_checkout", lambda: "9.9.9")
    assert autotrainer.core.__version__ == "9.9.9"
    with pytest.raises(AttributeError):
        autotrainer.core.not_a_real_attribute  # noqa
