# NB: this is to be back-compatible with h5 files possibly saved using pose_elements when they were defined
# in this sub-package (as autotrainer.inference.pose_elements)
from enum import Enum

from autotrainer.core import pose_elements
import sys
sys.modules[f"{__name__}.pose_elements"] = pose_elements
# this is/should be temporary. TODO: remove some when later


# must be before below other sub-imports
class InferenceStatus(str, Enum):
    stopped = "Stopped"
    loading = "Loading"
    waiting = "Waiting"
    live = "Live"
    intersession = "Intersession"
    stopping = "Stopping"


from .pose_algorithm import PoseAlgorithm, PoseResponse, PoseLocation, PoseTuple
from .pose_model import PoseModel
from .pose_process import PoseProcess, InferenceCommandMessageKind, InferenceStatusMessageKind, InferenceMode
from .memory import MemoryPoseModel
from .dlc import DlcPoseModel

