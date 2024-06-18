import numpy

from autotrainer.core import FixedArrayMultiQueue


def increase_buffer(buffer: FixedArrayMultiQueue, shape: (int, int), frames_per_camera: int, offset: int):
    content = numpy.zeros(shape, dtype=numpy.uint8)

    for idx in range(frames_per_camera):
        buffer.put(content + idx + offset, 1)
        buffer.put(content + idx + offset, 0)


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
