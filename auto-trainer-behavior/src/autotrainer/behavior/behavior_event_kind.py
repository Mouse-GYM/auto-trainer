from __future__ import annotations

from enum import Enum, IntEnum


class BehaviorEventKind(IntEnum, Enum):
    tunnelEnter = 1001
    tunnelExit = 1002,
    pelletLoadCan = 1201
    pelletLoadBegin = 1202,
    pelletLoadEnd = 1203,
    pelletSendCan = 1204
    pelletSendBegin = 1205,
    pelletSendEnd = 1206,
    pelletCoverCan = 1207
    pelletCoverBegin = 1208,
    pelletCoverEnd = 1209,
    pelletReleaseCan = 1210
    pelletReleaseBegin = 1211,
    pelletReleaseEnd = 1212,
    pelletAcknowledgeToken = 1298,
    pelletExternalToken = 1299,
    sessionStarted = 1301,
    sessionEnded = 1302,
    sessionPelletIncrease = 1311,
    sessionPelletDecrease = 1312,
    sessionMouseSeen = 1321,
    dayStarted = 1401,
    dayIncreasePellet = 1411,
    dayDecreasePellet = 1412,
    pelletSeen = 1501
    headfixBaselineChanged = 1601,
    headfixLoadCellChanged = 1602,
    headfixLoadCellChangedInIntersession = 1603,
    headfixLoadCellChangedWrongState = 1604,
    intersessionSegmentationCan = 1701,
    intersessionSegmentationBegin = 1702,
    intersessionSegmentationEnd = 1703,
    intersessionSegmentationNonceMismatch = 1704,
    intersessionSegmentationError = 1705,
    intersessionSegmentationSave = 1706,
    intersessionSegmentationSaveError = 1707,
    intersessionDetectionCan = 1711,
    intersessionDetectionBegin = 1712,
    intersessionDetectionEnd = 1713,
    intersessionDetectionNonceMismatch = 1714,
    intersessionDetectionError = 1715,
    intersessionDetectionSave = 1716,
    intersessionDetectionSaveError = 1717
