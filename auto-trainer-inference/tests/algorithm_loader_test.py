def test_loader():
    from autotrainer.inference import get_algorithm_packages

    packages = get_algorithm_packages()

    assert len(packages) == 0
