from collections import namedtuple

AlgorithmEntry = namedtuple("Plugin", ("name", "func"))

__Algorithms = {}


def register(*args):
    if len(args) > 0:
        name = args[0]
    else:
        name = None

    def decorator_repeat(func):
        package, _, plugin = func.__module__.rpartition(".")
        display_name = name or plugin
        pkg_info = __Algorithms.setdefault(package, {})
        pkg_info[plugin] = AlgorithmEntry(name=display_name, func=func)
        return func

    return decorator_repeat


def get_algorithm_packages():
    return list(__Algorithms.keys())


def get_algorithms_for_package(name):
    return __Algorithms[name]
