import numpy

from autotrainer.inference import PoseAlgorithm


def import_default_algorithm_module():
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("inference_algorithms", r"inference_algorithms/__init__.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["inference_algorithms"] = mod
    spec.loader.exec_module(mod)


def verify_algorithm(algorithms: dict, name: str, display_name: str, class_name: str):
    assert name in algorithms

    assert algorithms[name].name == display_name

    assert algorithms[name].func is not None

    pose_class = algorithms[name].func()

    assert pose_class.__class__.__name__ == class_name


def test_default_algorithm_location():
    from autotrainer.inference import get_algorithm_packages, get_algorithms_for_package

    import_default_algorithm_module()

    package_name = "inference_algorithms"

    packages = get_algorithm_packages()

    assert len(packages) == 1

    assert package_name in packages

    algorithms = get_algorithms_for_package(package_name)

    verify_algorithm(algorithms, "marker_only_pose_algorithm", "Marker Only", "MarkerOnlyPoseAlgorithm")

    verify_algorithm(algorithms, "pellet_only_pose_algorithm", "Pellet Only", "PelletOnlyPoseAlgorithm")


def verify_algorithm_output(algorithm: PoseAlgorithm, parts: list, data: numpy.ndarray):
    algorithm.set_parts(parts)

    algorithm.initialize()

    output = algorithm.process(data)

    assert len(output) == 2

    assert len(output[0]) == 4
    assert len(output[1]) == 4


def test_algorithm_output():
    from inference_algorithms import PelletOnlyPoseAlgorithm, MarkerOnlyPoseAlgorithm
    from autotrainer.inference import get_algorithms_for_package

    import_default_algorithm_module()

    package_name = "inference_algorithms"

    algorithms = get_algorithms_for_package(package_name)

    rng = numpy.random.default_rng()

    data = rng.standard_normal((6, 30), dtype=numpy.float32)

    parts = ["Pellet", "Star", "Other3", "Other4", "Other5", "Other6", "Other7", "Other8", "Other9", "Other10"]

    pose_class: PelletOnlyPoseAlgorithm = algorithms["pellet_only_pose_algorithm"].func()

    verify_algorithm_output(pose_class, parts, data)

    marker_class: MarkerOnlyPoseAlgorithm = algorithms["pellet_only_pose_algorithm"].func()

    verify_algorithm_output(marker_class, parts, data)
