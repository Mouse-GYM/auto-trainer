import functools
import importlib
import importlib.metadata
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Optional


PLACEHOLDER_VERSION = "0.0.0"
DISTRIBUTION_NAME = "auto-trainer-core"

_package_dir = Path(__file__).resolve().parent


def _has_setuptools_scm() -> bool:
    return importlib.util.find_spec("setuptools_scm") is not None


def _version_from_checkout(package_dir: Path = _package_dir) -> Optional[str]:
    # only a source layout (<project>/src/autotrainer/core) inside a git checkout is worth a subprocess:
    # an installed copy lives in site-packages and gets its version from the generated file or the metadata
    src_dir = package_dir.parent.parent
    if src_dir.name != "src":
        return None
    project_dir = src_dir.parent
    if not project_dir.joinpath("pyproject.toml").is_file():
        return None
    # .exists(), not .is_dir(): .git is a file in a worktree
    if not any(directory.joinpath(".git").exists() for directory in (project_dir, *project_dir.parents)):
        return None
    if not _has_setuptools_scm():
        return None
    try:
        # cwd supplies core's pyproject.toml, hence the core-v* tag pattern and the parent-directory search
        out = subprocess.check_output(
            [sys.executable, "-m", "setuptools_scm"], cwd=project_dir, stderr=subprocess.DEVNULL, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.decode().strip() or None


def _version_from_file() -> Optional[str]:
    try:
        # through importlib: the module only exists after a build
        version_module = importlib.import_module(f"{__package__}._version")
    except ImportError:
        return None
    return getattr(version_module, "version", None)


def _version_from_metadata() -> Optional[str]:
    try:
        return importlib.metadata.version(DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError:
        return None


@functools.lru_cache(maxsize=None)
def get_version() -> str:
    for source in (_version_from_checkout, _version_from_file, _version_from_metadata):
        version = source()
        if version:
            return version
    return PLACEHOLDER_VERSION
