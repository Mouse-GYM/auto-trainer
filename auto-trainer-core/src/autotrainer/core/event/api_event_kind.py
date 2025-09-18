from enum import IntEnum, Enum


# Note: This also inherits from Enum and does not follow the Python underscore naming convention so they are presented
# in event logs and other output in the desired format without needing to custom format everywhere.
class ApiEventKind(IntEnum, Enum):
    """
    See EventManager for a description and purpose of API events.

    0000-0999   Core/System
    1000-1999   Behavior
    2000-2999   Device
    3000-3999   Inference
    4000-4999   Analysis
    9000-9999   Application
    """

    # Core/System
    emergencyStop = 101
    emergencyResume = 102

    # Behavior
    algorithmPause = 1001
    algorithmResume = 1002

    tunnelEnter = 1101
    tunnelExit = 1102

    pelletLoadCan = 1201
    pelletLoadBegin = 1202
    pelletLoadEnd = 1203
    pelletSendCan = 1204
    pelletSendBegin = 1205
    pelletSendEnd = 1206
    pelletCoverCan = 1207
    pelletCoverBegin = 1208
    pelletCoverEnd = 1209
    pelletReleaseCan = 1210
    pelletReleaseBegin = 1211
    pelletReleaseEnd = 1212
    pelletHomeCan = 1213
    pelletHomeBegin = 1214
    pelletHomeEnd = 1215
    pelletPrereleaseCan = 1216
    pelletPrereleaseBegin = 1217
    pelletPrereleaseEnd = 1218
    pelletAcknowledgeToken = 1298
    pelletExternalToken = 1299

    sessionStarting = 1301
    sessionStarted = 1302
    sessionEnding = 1303
    sessionEnded = 1304
    sessionPelletIncrease = 1311
    sessionPelletDecrease = 1312
    sessionMouseSeen = 1321

    dayStarted = 1401
    dayIncreasePellet = 1411
    dayDecreasePellet = 1412

    pelletSeen = 1501
    pelletPresented = 1502
    pelletSuccessfulReach = 1503

    triangleSeen = 1550

    headfixBaselineChanged = 1601
    headfixLoadCellChanged = 1602
    headfixLoadCellChangedInIntersession = 1603
    headfixLoadCellChangedWrongState = 1604
    headfixAutoTare = 1611

    autoClampIntensityChanged = 1621
    autoClampReleaseToneFreqChanged = 1622
    autoClampReleaseDelayChanged = 1623

    intersessionSegmentationCan = 1701
    intersessionSegmentationBegin = 1702
    intersessionSegmentationEnd = 1703
    intersessionSegmentationNonceMismatch = 1704
    intersessionSegmentationError = 1705
    intersessionSegmentationSave = 1706
    intersessionSegmentationSaveError = 1707
    intersessionSegmentationInputError = 1708
    intersessionDetectionCan = 1711
    intersessionDetectionBegin = 1712
    intersessionDetectionEnd = 1713
    intersessionDetectionNonceMismatch = 1714
    intersessionDetectionError = 1715
    intersessionDetectionSave = 1716
    intersessionDetectionSaveError = 1717
    intersessionShiftX = 1731
    intersessionShiftY = 1732
    intersessionShiftZ = 1733

    headFixationForceDetectorChanged = 1801
    headFixationEnabled = 1802

    # Device
    deviceCommandSend = 2001
    deviceCommandAcknowledge = 2002

    # Analysis
    loadCellEngagedChanged = 4001
    headbarPressureEngagedChanged = 4011
