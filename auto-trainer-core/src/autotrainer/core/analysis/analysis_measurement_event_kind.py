from enum import Enum, IntEnum


# Note: This also inherits from Enum and do not follow the Python underscore naming convention so they are presented in
# event logs and other output in the desired format without needing to custom format everywhere.

class AnalysisMeasurementEventKind(IntEnum, Enum):
    loadCellEngagedChanged = 2001
    headbarPressureEngagedChanged = 2002
