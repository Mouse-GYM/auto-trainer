
from enum import Enum
from typing import Dict

_cache_scene_elements: Dict[str, "BaseSceneElement"] = {}


class BaseSceneElement(str):  # , Enum):
    """Dedicated str subclass for scene elements,
    main feature is to have the created elements be all cached/singleton,
    allowing use of "is" operator comparison with previous reference to any of them.
    """
    # we might want to use something more flexible, if the model would not use same names than here,
    # like with a mapping dict, and some dynamic attributes + type hints on the class to still help development.

    def __new__(cls, value: str):
        cached = _cache_scene_elements.get(value, None)
        if cached is None:
            tentative = super().__new__(cls, value)
            assert isinstance(tentative, BaseSceneElement)
            cached = _cache_scene_elements.setdefault(value, tentative)  # threads-safe
        return cached

    @property
    def value(self):
        # was using an Enum subclass previously, and code still using this ".value" property.
        return self


class SceneElement(BaseSceneElement):

    Pellet = BaseSceneElement('Pellet')

    R_Hand = BaseSceneElement('R_Hand')
    RH_flat = BaseSceneElement('RH_flat')
    RH_spread = BaseSceneElement('RH_spread')
    RH_grab = BaseSceneElement('RH_grab')

    L_Hand = BaseSceneElement('L_Hand')
    LH_flat = BaseSceneElement('LH_flat')
    LH_spread = BaseSceneElement('LH_spread')
    LH_grab = BaseSceneElement('LH_grab')

    Nose = BaseSceneElement('Nose')
    Mouth = BaseSceneElement('Mouth')
    Tongue_mid = BaseSceneElement('Tongue_mid')
    Tongue_tip = BaseSceneElement('Tongue_tip')

    Star = BaseSceneElement('Star')
    Diamond = BaseSceneElement('Diamond')
    Triangle = BaseSceneElement('Triangle')

    def __new__(cls, value):
        return BaseSceneElement(value)
