import pytest

from autotrainer.inference.pose_elements import SceneElement, BaseSceneElement


def test_scene_element_base():
    assert SceneElement.Diamond == "Diamond"


@pytest.mark.parametrize('base_cls', [BaseSceneElement, SceneElement])
def test_scene_element_singleton(base_cls):
    assert base_cls('Diamond') is SceneElement.Diamond
