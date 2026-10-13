from pathlib import Path

import pytest

from autotrainer.core.diamond_triangle_config import DiamondTriangleOffsetConfig


fixtures_path = Path(__file__).parent.joinpath("fixtures")


@pytest.fixture(autouse=True)
def diamond_config_path(monkeypatch):
    path = fixtures_path.joinpath("diamond_triangle_offset.yaml")
    monkeypatch.setattr(DiamondTriangleOffsetConfig, "DEFAULT_CONFIG_PATH", path)
    assert DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH is path
    return path
