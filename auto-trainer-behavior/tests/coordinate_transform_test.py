
import numpy as np

from autotrainer.behavior import DiamondTriangleOffsetConfig
from autotrainer.core import Offset3DTuple

import pytest


@pytest.fixture()
def diamond_triangle_config():
    return DiamondTriangleOffsetConfig(
        used_position=Offset3DTuple(8, 15, 10),
        measured_offset=Offset3DTuple(5, -7, -9),
    )


@pytest.mark.parametrize("motor_xyz", [
    (-3, -9, 7),
    (0, 0, 0),
    (1, 2, 3),
    (4, 5, 6),
    (15, 8, 12),
])
def test_transform_coordinates(motor_xyz, diamond_triangle_config):
    cfg = diamond_triangle_config
    motor_xyz = Offset3DTuple(motor_xyz)
    diamond_xyz = cfg.motor_to_diamond(motor_xyz)
    assert np.isclose(cfg.diamond_to_motor(diamond_xyz), motor_xyz).all()
    inference_xyz = cfg.motor_to_inference(motor_xyz)
    assert np.isclose(cfg.inference_to_motor(inference_xyz), motor_xyz).all()
    assert np.isclose(cfg.inference_to_diamond(inference_xyz), diamond_xyz).all()
