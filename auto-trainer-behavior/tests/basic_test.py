import pytest

from autotrainer.core import Offset3DTuple
from autotrainer.behavior import DiamondTriangleOffsetConfig


zero_offset = Offset3DTuple(0, 0, 0)
one_offset = Offset3DTuple(1, 1, 1)

def test_diamond_triangle_offset_config_with_args_fail():
    with pytest.raises(TypeError):
        DiamondTriangleOffsetConfig(zero_offset, zero_offset)


def test_diamond_triangle_offset_config_kwargs():
    cfg = DiamondTriangleOffsetConfig(used_position=zero_offset, measured_offset=one_offset)
    assert cfg.used_position is zero_offset
    assert cfg.measured_offset is one_offset
