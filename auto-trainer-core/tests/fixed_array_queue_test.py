from functools import partial

import numpy

from autotrainer.core import FixedArrayMultiQueue


def increase_buffer(buffer: FixedArrayMultiQueue, shape: (int, int), frames_per_camera: int, offset: int):
    content = numpy.zeros(shape, dtype=numpy.uint8)

    for idx in range(frames_per_camera):
        buffer.put(content + idx + offset, 1, 0)
        buffer.put(content + idx + offset, 0, 0)


def check_buffer(buffer: FixedArrayMultiQueue, shape: (int, int), frames_per_camera: int, expected_index: int):
    output = numpy.zeros((frames_per_camera * 2, *shape, 3), dtype=numpy.uint8)

    result = buffer.get_output(output)

    assert result is True

    assert buffer.buffer_index == expected_index

    assert buffer.get_output(output) is False


def test_buffer():
    shape = (200, 300)

    frames_per_camera = 5

    buffer = FixedArrayMultiQueue(3, 2, frames_per_camera, shape)

    assert buffer.buffer_index == 0

    increase_buffer(buffer, shape, frames_per_camera, 1)

    check_buffer(buffer, shape, frames_per_camera, 1)

    increase_buffer(buffer, shape, frames_per_camera, 6)

    check_buffer(buffer, shape, frames_per_camera, 2)

    increase_buffer(buffer, shape, frames_per_camera, 11)

    check_buffer(buffer, shape, frames_per_camera, 0)


def test_get_cam_missing_frames():
    shape = (100, 100)
    frames_per_cam = 3
    buffer = FixedArrayMultiQueue(3, 2, frames_per_cam, shape)
    content = numpy.zeros(shape, dtype=numpy.uint8)
    #
    check_missing = buffer.get_cam_missing_frames
    put_cam_0 = lambda: buffer.put(content, 0, 0)
    put_cam_1 = lambda: buffer.put(content, 1, 0)

    increase_buffer(buffer, shape, 2, 0)
    assert check_missing(0) == frames_per_cam - 2  # 1
    assert check_missing(1) == frames_per_cam - 2  # 1
    increase_buffer(buffer, shape, 2, 0)
    assert check_missing(0) == frames_per_cam - 1
    assert check_missing(1) == frames_per_cam - 1

    put_cam_0()
    put_cam_0()
    assert check_missing(0) == 0
    assert check_missing(1) == frames_per_cam - 1

    put_cam_0()
    assert check_missing(0) == 2
    assert check_missing(1) == 2 * frames_per_cam - 1  # 5

    put_cam_1()
    assert check_missing(0) == 2  # still
    assert check_missing(1) == frames_per_cam + 1  # 4

    put_cam_0()
    assert check_missing(0) == 1  # now
    assert check_missing(1) == frames_per_cam + 1  # 4 still

    put_cam_0()
    assert check_missing(0) == 0  # now
    assert check_missing(1) == frames_per_cam + 1  # 4 still

    put_cam_1()
    assert check_missing(0) == 0  # now
    assert check_missing(1) == frames_per_cam  # 3

    put_cam_1()
    assert check_missing(0) == 0  # now
    assert check_missing(1) == frames_per_cam - 1  # 2