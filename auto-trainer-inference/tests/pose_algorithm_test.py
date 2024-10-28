import typing

import numpy

from autotrainer.inference import PoseAlgorithm
from autotrainer.inference import PoseResponse, PoseLocation


def verify_common_output(response: PoseResponse, sequence: int, parts: typing.List[str]):
    assert response.sequence == sequence

    num_parts = len(parts)

    assert response.parts_flag and len(response.parts_flag) == num_parts

    assert response.locations and len(response.locations) == 2

    locations = response.locations[0]

    assert len(locations) == num_parts

    locations = response.locations[1]

    assert len(locations) == num_parts


def verify_all_false(flags: typing.Dict[str, bool], except_part: int = -1):
    for idx, val in enumerate(flags.values()):
        if idx != except_part:
            assert val is False
        else:
            assert val is True


def verify_all_empty(locations_list: typing.List[typing.List[PoseLocation]], except_camera: int = -1,
                     except_part: int = -1):
    for cdx, locations in enumerate(locations_list):
        for idx, location in enumerate(locations):
            assert location is not None
            assert location.index == idx
            assert location.name == f"Part{idx:02}"
            if cdx == except_camera and idx == except_part:
                assert location.x != -1
                assert location.y != -1
            else:
                assert location.x == -1
                assert location.y == -1


def test_algorithm_output():
    data = list()

    # Ensure all confidence values will be below the default thresholds (/2).
    for idx in range(6):
        data.append(numpy.random.rand(10, 3) / 2)

    parts = ["Part00", "Part01", "Part02", "Part03", "Part04", "Part05", "Part06", "Part07", "Part08", "Part09"]

    algorithm = PoseAlgorithm()

    algorithm.initialize(parts)

    response = algorithm.process(data)

    verify_common_output(response, 1, parts)

    verify_all_false(response.parts_flag)

    verify_all_empty(response.locations)

    # Set the confidence for a part in a middle frame above the plot and seen thresholds.
    data[3][5][2] = 0.95

    response = algorithm.process(data)

    verify_common_output(response, 2, parts)

    verify_all_false(response.parts_flag, 5)

    # Interleaved frame 3 changed above is for the right/second camera.
    verify_all_empty(response.locations, 1, 5)


if __name__ == '__main__':
    test_algorithm_output()
