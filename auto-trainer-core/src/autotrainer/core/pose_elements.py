
import dataclasses
import math
from enum import Enum
from typing import Dict


_cache_scene_elements: Dict[str, "_BaseSceneElement"] = {}
_cache_scene_elements_str: Dict[str, str] = {}


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
        cached_str = _cache_scene_elements_str.setdefault(value, str(cached))
        return cached_str


class SceneElement(_BaseSceneElement):

    Pellet: "SceneElement" = 'Pellet'

    R_Hand: "SceneElement" = 'R_Hand'  # composite element part
    RH_flat: "SceneElement" = 'RH_flat'
    RH_spread: "SceneElement" = 'RH_spread'
    RH_grab: "SceneElement" = 'RH_grab'

    L_Hand: "SceneElement" = 'L_Hand'  # composite element part
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

    AnyAnimalPart: "SceneElement" = 'AnyAnimalPart'


AllHandsParts = (
    SceneElement.RH_flat, SceneElement.RH_spread, SceneElement.RH_grab,
    SceneElement.LH_flat, SceneElement.LH_spread, SceneElement.LH_grab,
)


AllAnimalParts = (
    SceneElement.Nose,
    SceneElement.Mouth,
    SceneElement.Tongue_tip,
    SceneElement.Tongue_mid,
) + AllHandsParts


AllNonAnimalParts = (
    SceneElement.Pellet,
    SceneElement.Diamond,
    SceneElement.Triangle,
    SceneElement.Star,
)


AllSceneParts = AllAnimalParts + AllNonAnimalParts


@dataclasses.dataclass
class ScenePartsContext:

    parts_present_last_perf_c: Dict[str, float]  # last presence change perf counter
    parts_missing_last_perf_c: Dict[str, float]  # last absence change perf counter

    def get_part_presence_age(self, part: str, perf_now: float) -> float:
        presence_p = self.parts_present_last_perf_c.get(part, None)
        absence_p = self.parts_missing_last_perf_c.get(part, None)
        if presence_p is None or (absence_p is not None and absence_p > presence_p):
            return 0
        return perf_now - presence_p

    def get_part_absence_age(self, part: str, perf_now: float) -> float:
        presence_p = self.parts_present_last_perf_c.get(part, None)
        absence_p = self.parts_missing_last_perf_c.get(part, None)
        if absence_p is None:
            return math.inf
        if presence_p is not None and presence_p > absence_p:
            return 0
        return perf_now - absence_p
