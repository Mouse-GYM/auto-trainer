
import sys
import subprocess
import warnings


if sys.version_info[:2] >= (3, 10):
    import importlib.resources as importlib_resources
    import importlib.metadata as importlib_metadata
else:
    import importlib_resources
    import importlib_metadata


# always get from setuptools-scm (git) if available:

def _get_from_setuptools_scm():
    try:
        import setuptools_scm
    except ImportError:
        return None
    try:
        out = subprocess.check_output([sys.executable, "-m", "setuptools_scm"])
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
            __version__ = importlib_metadata.version("autotrainer")
        except importlib_metadata.PackageNotFoundError:
            import warnings
            warnings.warn(f"autotrainer version not available, all bets are off, "
                          f"was project installed at all ?")
            __version__ = "0.0.0"
