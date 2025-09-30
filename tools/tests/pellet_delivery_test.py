
import numpy as np

from autotrainer.behavior import DiamondTriangleOffsetConfig
from autotrainer.core import Offset3DTuple

from tools.pellet_delivery.model.app_model import AppModel


import pytest


@pytest.fixture()
def diamond_triangle_config_path(tmp_path):
    p = tmp_path.joinpath("diamond_triangle_config.yaml")
    cfg = DiamondTriangleOffsetConfig(
        used_position=Offset3DTuple(8, 15, 10),
        measured_offset=Offset3DTuple(5, -7, -9),
    )
    cfg.to_file(p)
    yield p


@pytest.mark.parametrize("motor_xyz", [
    (0, 0, 0),
    (1, 2, 3),
    (4, 5, 6),
    (15, 8, 12),
])
def test_transform_coordinates(motor_xyz, diamond_triangle_config_path):
    app_model = AppModel(diamond_triangle_config_path=diamond_triangle_config_path)
    motor_xyz = Offset3DTuple(motor_xyz)
    diamond_xyz = app_model.to_diamond_coordinates(motor_xyz)
    assert np.isclose(app_model.to_motor_coordinates(diamond_xyz), motor_xyz).all()
