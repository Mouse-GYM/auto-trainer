
import sys
import subprocess
import warnings
from pathlib import Path


if sys.version_info[:2] >= (3, 10):
    import importlib.resources as importlib_resources
    import importlib.metadata as importlib_metadata
else:
    import importlib_resources
    import importlib_metadata


top_dir = Path(__file__).parent.parent.resolve()
# .parent -> tools dir
# .parent.parent -> top dir


# always get from setuptools-scm (git) if available:

def _get_from_setuptools_scm():
    try:
        import setuptools_scm
    except ImportError:
        return None
    if not top_dir.joinpath(".git").is_dir():
        return None
    try:
        out = subprocess.check_output([sys.executable, "-m", "setuptools_scm"], cwd=top_dir)
    except subprocess.CalledProcessError as err:
        # warnings.warn(f"setuptools_scm failed to get version: {err}", UserWarning)
        return None
    out = out.decode().strip()
    return out if len(out) > 0 else None


__version__ = _get_from_setuptools_scm()

if __version__ is None:
    # otherwise, get from version txt file:
    try:
        __version__ = importlib_resources.files("tools").joinpath("autotrainer_version.txt").read_text().strip()
    except (ModuleNotFoundError, FileNotFoundError):
        # and finally try to use metadata:
        try:
            __version__ = importlib_metadata.version("auto-trainer")
        except importlib_metadata.PackageNotFoundError:
            warnings.warn("auto-trainer version not available, all bets are off, "
                          "was project installed at all ?")
            __version__ = "0.0.0"
