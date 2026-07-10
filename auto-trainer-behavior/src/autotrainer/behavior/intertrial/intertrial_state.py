from enum import Enum

class IntertrialState(str, Enum):
    idle = "idle"
    segmentation = "segmentation"
    detection = "detection"
