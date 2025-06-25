
from enum import Enum
from typing import Dict

_cache_scene_elements: Dict[str, "_BaseSceneElement"] = {}


class _BaseSceneElement(str):  # , Enum):
    """Dedicated str subclass for scene elements,
    main feature is to have the created elements be all cached/singleton,
    allowing use of "is" operator comparison with previous reference to any of them.
    """
    # we might want to use something more flexible, if the model would not use same names than here,
    # like with a mapping dict, and some dynamic attributes + type hints on the class to still help development.

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # set all string values to SceneElement/cls instance,
        # which pre-loads it in _cache_scene_elements:
        for name, value in vars(cls).items():
            if cls.__annotations__.get(name) != 'SceneElement' or not isinstance(value, str):
                continue
            setattr(cls, name, cls(value))

    def __new__(cls, value: str):
        cached = _cache_scene_elements.get(value, None)
        if cached is None:
            tentative = super().__new__(cls, value)
            assert isinstance(tentative, _BaseSceneElement)
            cached = _cache_scene_elements.setdefault(value, tentative)  # threads-safe
        # return the raw str value:
        # otherwise, when used as column(multiindex or not) and in h5 files that will make
        # the column to be saved with pickle,
        # which when unpickled fails if the pickled object type has been moved meanwhile.
        return str(cached)


class SceneElement(_BaseSceneElement):

    Pellet: "SceneElement" = 'Pellet'

    R_Hand: "SceneElement" = 'R_Hand'
    RH_flat: "SceneElement" = 'RH_flat'
    RH_spread: "SceneElement" = 'RH_spread'
    RH_grab: "SceneElement" = 'RH_grab'

    L_Hand: "SceneElement" = 'L_Hand'
    LH_flat: "SceneElement" = 'LH_flat'
    LH_spread: "SceneElement" = 'LH_spread'
    LH_grab: "SceneElement" = 'LH_grab'

    Nose: "SceneElement" = 'Nose'
    Mouth: "SceneElement" = 'Mouth'
    Tongue_mid: "SceneElement" = 'Tongue_mid'
    Tongue_tip: "SceneElement" = 'Tongue_tip'

    Star: "SceneElement" = 'Star'
    Diamond: "SceneElement" = 'Diamond'
    Triangle: "SceneElement" = 'Triangle'
