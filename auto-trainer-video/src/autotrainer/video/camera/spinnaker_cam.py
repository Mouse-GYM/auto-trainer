import ast
import atexit
import dataclasses
import logging
from enum import IntEnum
from typing import Tuple, List, Dict, Optional, Type

import numpy
import PySpin

from autotrainer.core.logging import get_verbose_logger

from .camera_base import CameraBase


logger = get_verbose_logger(__name__)

def is_truthy_str_value(value: str):
    return value.lower() in {"true", "yes", "on", "1"}


sSystem = None

def _start_spincam_lib_instance():
    global sSystem
    if sSystem is None:
        logger.info("getting spincam library instance")
        sSystem = PySpin.System.GetInstance()
        if sSystem is None:
            raise RuntimeError("PySpin.System.GetInstance() returned None")
    return sSystem


def _stop_spincam_lib_instance(cls: Type["SpinCam"]):
    global sSystem
    for key, spincam in list(cls._cameras.items()):  # loop over list copy of items,
        # given _release_spincam() will modify `cls._cameras` dict
        try:
            spincam.end_capture()
        except Exception as err:
            logger.exception("Error ending capture on %s: %s", spincam.name, err)
    cls._cameras.clear()
    if sSystem is not None:
        logger.info("releasing SpinCam lib")
        sSystem.ReleaseInstance()
        sSystem = None


class AcquisitionMode(IntEnum):
    Continuous = 0
    SingleFrame = 1
    MultiFrame = 2


@dataclasses.dataclass
class SpinCamDefaultParams:
    exposure: float = 140
    fps: int = 150
    hbin: int = 4
    vbin: int = 4
    width: int = 256
    height: int = 256
    offsetx: int = 52
    offsety: int = 6
    gain: float = 1
    gamma: float = 0.7


class SpinCam(CameraBase):

    _cameras: Dict[str, "SpinCam"] = {}  # class level cache

    default_params = dataclasses.asdict(SpinCamDefaultParams())

    @classmethod
    def list(cls) -> List[str]:
        _start_spincam_lib_instance()
        serial_numbers = []
        cam_list = sSystem.GetCameras()
        try:
            for cam in cam_list:
                serial_numbers.append(cam.TLDevice.DeviceSerialNumber.ToString())
        finally:
            cam_list.Clear()
        return serial_numbers

    @classmethod
    def create(cls, serial_number: str, name: str = ""):
        if serial_number in cls._cameras:
            return cls._cameras[serial_number]
        obj = SpinCam(serial_number, name)
        cls._cameras[serial_number] = obj
        return obj

    def __init__(self, serial_number, name: str = ""):

        self._camera: Optional[PySpin.Camera] = None
        self._node_map = None
        self._node_map_tl_device = None
        self._start_frames = []

        super().__init__(name)

        self._serial_number = serial_number

        def get_def(k):
            v = self.default_params.get(k)
            if v is None:
                logger.verbose("No default for param %r", k)
            return v

        self._exposure = get_def("exposure")
        self._fps = get_def("fps")
        self._horizontal_binning = get_def("hbin")
        self._vertical_binning = get_def("vbin")
        self._width = get_def("width")
        self._height = get_def("height")
        self._offset_x = get_def("offsetx")
        self._offset_y = get_def("offsety")

        self._gain: Optional[float] = get_def("gain")
        self._gamma: Optional[float] = get_def("gamma")

        self._is_primary = False
        self._is_secondary = True

        self._acquisition_started = False
        self._skip_duplicate_frame_copy = False

        _start_spincam_lib_instance()

        cam_list = sSystem.GetCameras()
        try:
            self._camera = cam_list.GetBySerial(serial_number)
        finally:
            cam_list.Clear()

        # not needed
        # self._image_processor = PySpin.ImageProcessor()
        # self._image_processor.SetColorProcessing(PySpin.SPINNAKER_COLOR_PROCESSING_ALGORITHM_HQ_LINEAR)

    def __del__(self):
        self.end_capture()

    @property
    def fps(self) -> float:
        return self._fps

    @fps.setter
    def fps(self, value: float) -> None:
        self._fps = value

    @property
    def width(self):
        return self._width

    @width.setter
    def width(self, value):
        self._width = value

    @property
    def height(self):
        return self._height

    @height.setter
    def height(self, value):
        self._height = value

    @property
    def offset_x(self):
        return self._offset_x

    @offset_x.setter
    def offset_x(self, value):
        self._offset_x = value

    @property
    def offset_y(self):
        return self._offset_y

    @offset_y.setter
    def offset_y(self, value):
        self._offset_y = value

    @property
    def horizontal_binning(self) -> int:
        return self._horizontal_binning

    @horizontal_binning.setter
    def horizontal_binning(self, value: int) -> None:
        self._horizontal_binning = value

    @property
    def vertical_binning(self) -> int:
        return self._vertical_binning

    @vertical_binning.setter
    def vertical_binning(self, value: int) -> None:
        self._vertical_binning = value

    @property
    def exposure(self) -> int:
        return self._exposure

    @exposure.setter
    def exposure(self, value: int) -> None:
        self._exposure = value

    def _reinit_cam(self):
        spincam = self._camera
        logger.notice("doing cam reset with begin+end acquisition")
        # Stackoverflow 64660434.  Apparently there is no simple reset/release call to fix when it is in this state.
        spincam.BeginAcquisition()
        spincam.EndAcquisition()
        spincam.DeInit()
        spincam.Init()

    def init(self):
        spincam = self._camera
        spincam.Init()

        self._acquisition_started = False

        self._node_map = spincam.GetNodeMap()

        if spincam.Width.GetAccessMode() != PySpin.RW:
            self._reinit_cam()

        node_acquisition_mode = PySpin.CEnumerationPtr(self._node_map.GetNode('AcquisitionMode'))

        node_acquisition_mode.SetIntValue(AcquisitionMode.Continuous.value)

        if spincam.ExposureAuto.GetAccessMode() == PySpin.RW:
            spincam.ExposureAuto.SetValue(PySpin.ExposureAuto_Off)
            logger.debug(f"<{self._name}> ExposureAuto set to {spincam.ExposureAuto.GetValue()}")
        else:
            logger.warning(f"<{self._name} ExposureAuto is not writeable")

        if spincam.GainAuto.GetAccessMode() == PySpin.RW:
            spincam.GainAuto.SetValue(PySpin.GainAuto_Off)
            logger.debug(f"<{self._name}> GainAuto set to {spincam.GainAuto.GetValue()}")
        else:
            logger.warning(f"<{self._name} GainAuto is not writeable")

        if spincam.Gain.GetAccessMode() == PySpin.RW:
            spincam.Gain.SetValue(0)
            logger.debug(f"<{self._name}> Gain set to {spincam.Gain.GetValue()}")
        else:
            logger.warning(f"<{self._name} Gain is not writeable")

        s_node_map = spincam.GetTLStreamNodeMap()
        handling_mode = PySpin.CEnumerationPtr(s_node_map.GetNode("StreamBufferHandlingMode"))
        if not PySpin.IsAvailable(handling_mode) or not PySpin.IsWritable(handling_mode):
            logger.warning(f"<{self._name} unable to set Buffer Handling mode (node retrieval)")
        else:
            handling_mode_entry = handling_mode.GetEntryByName("OldestFirst")
            handling_mode.SetIntValue(handling_mode_entry.GetValue())

        self._apply_settings()

    def _apply_settings(self):
        # exposure first:
        self._set_bounded_int_property_node(self._camera.ExposureTime, self._exposure)
        # then FPS:
        self._camera.AcquisitionFrameRateEnable.SetValue(True)
        self._camera.AcquisitionFrameRate.SetValue(self._fps)

        # binning first
        self._set_bounded_int_property_node(self._camera.BinningHorizontal, self._horizontal_binning)
        self._set_bounded_int_property_node(self._camera.BinningVertical, self._vertical_binning)

        # then size:
        self._set_bounded_int_property_node(self._camera.Width, self._width)
        self._set_bounded_int_property_node(self._camera.Height, self._height)

        # then offset:
        # self.offset_x = self._offset_x
        self._set_bounded_int_property_node(self._camera.OffsetX, self._offset_x)
        self._set_bounded_int_property_node(self._camera.OffsetY, self._offset_y)

        if self._gain is not None:
            self._set_bounded_float_property_node(self._camera.Gain, self._gain)

        gamma = self._gamma
        if gamma is not None:
            self._set_bounded_bool_property_node(self._camera.GammaEnable, True)
            self._set_bounded_float_property_node(self._camera.Gamma, gamma)
        else:
            self._set_bounded_bool_property_node(self._camera.GammaEnable, False)

    def prepare_capture(self):
        super().prepare_capture()

        if self._is_primary == self._is_secondary:
            raise RuntimeError("Camera %s configured as both primary and secondary", self._name)

        if self._is_primary:
            self._configure_as_primary()
            logger.info(f"<{self.name}> configured as primary")

        elif self._is_secondary:
            self._configure_as_secondary()
            logger.info(f"<{self.name}> configured as secondary")

    def end_capture(self):
        super().end_capture()
        spincam = self._camera
        if spincam is None:
            return
        spincam.EndAcquisition()
        if self._is_primary:
            spincam.LineSelector.SetValue(PySpin.LineSelector_Line1)
            spincam.LineSource.SetValue(PySpin.LineSource_FrameTriggerWait)
            spincam.LineInverter.SetValue(True)
        elif self._is_secondary:
            spincam.TriggerMode.SetValue(PySpin.TriggerMode_Off)
        spincam.DeInit()
        self._cameras.pop(self._serial_number, None)
        logger.debug("released spincam for %s (%s)", self._name, self._serial_number)
        self._camera = None

    def capture(self) -> Tuple[numpy.ndarray, int]:
        first_capture = False
        if not self._acquisition_started:
            self._acquisition_started = True
            first_capture = True
            logger.info("Beginning acquisition ; skip_dup_copy=%s", self._skip_duplicate_frame_copy)
            self._camera.BeginAcquisition()
            if self._is_primary:
                self._camera.LineSelector.SetValue(PySpin.LineSelector_Line1)
                self._camera.LineSource.SetValue(PySpin.LineSource_Counter0Active)
                self._camera.TriggerMode.SetValue(PySpin.TriggerMode_Off)

        expected_shape = (self._height, self._width)

        image_result = self._camera.GetNextImage()
        if image_result.IsIncomplete():
            # fail early
            image_result.Release()
            raise RuntimeError(f"Incomplete spincam image on frame_idx={self._frame_count}")

        self._last_when = image_result.GetTimeStamp()
        self._last_frame_id = image_result.GetFrameID()

        frame = orig_frame = image_result.GetNDArray()  # get the frame/array as acquired by hardware itself
        # image_converted = self._image_processor.Convert(image_result, PySpin.PixelFormat_Mono8)
        # frame = image_converted.GetNDArray()
        # reminder: the frame we get directly from camera is already in our desired format (shape + dtype).

        if first_capture:
            self._capture_start = self._last_when
            logger.notice("first frame: shape=%s (expected=%s) dtype=%s itemsize=%s",
                          frame.shape, expected_shape, frame.dtype, frame.itemsize)
            if frame.shape != expected_shape:
                logger.warning("Frame shape not as expected: %s vs %s", frame.shape, expected_shape)

        if not self._skip_duplicate_frame_copy:
            frame = frame.copy()

        image_result.Release()

        if frame.shape != expected_shape:
            frame = frame.reshape(expected_shape)

        if __debug__:
            # ensure no frame in the first 150, shares its internal buffer with any of the other first 150 of them:
            if self._frame_count < 150:
                logger.spam("frame-%s: shape=%s dtype=%s",
                             self._frame_count, orig_frame.shape, orig_frame.dtype)
                self._start_frames.append((orig_frame, orig_frame.copy()))
                for prev_idx, (prev_frame, prev_frame_copy) in enumerate(self._start_frames):
                    if (prev_frame != prev_frame_copy).any():
                        logger.critical("Detected prev frame (idx=%s) got corrupted", prev_idx)
                    if prev_idx == self._frame_count:
                        break
                    if (orig_frame == prev_frame).all() and (orig_frame != prev_frame_copy).any():
                        logger.critical("Detected frame (idx=%s) shares internal buffer with prev frame idx=%s",
                                        self._frame_count, prev_idx)
                if self._frame_count >= 149:
                    self._start_frames.clear()  # don't keep unnecessarily all that

        self._frame_count += 1

        return frame, self._last_when

    def set_property(self, name: str, value: str) -> bool:
        if name == "primary":
            self._is_primary = is_truthy_str_value(value)
            self._is_secondary = not self._is_primary
        elif name == "secondary":
            self._is_secondary = is_truthy_str_value(value)
            self._is_primary = not self._is_secondary
        elif name in {"offsetx", "offset_x"}:
            self.offset_x = int(value)
        elif name in {"offsety", "offset_y"}:
            self.offset_y = int(value)
        elif name == "hbin":
            self.horizontal_binning = int(value)
        elif name == "vbin":
            self.vertical_binning = int(value)
        elif name == "exposure":
            self.exposure = int(value)
        elif name == "gain":
            self._gain = ast.literal_eval(value)  # allows None or float (or actually any literal)
        elif name == "gamma":
            self._gamma = ast.literal_eval(value)  # allows None or float (or actually any literal)
        elif name == "skip_duplicate_frame_copy":
            self._skip_duplicate_frame_copy = is_truthy_str_value(value)
        else:
            return super().set_property(name, value)

        return True

    def _configure_as_primary(self):
        self._camera.CounterSelector.SetValue(PySpin.CounterSelector_Counter0)
        self._camera.CounterEventSource.SetValue(PySpin.CounterEventSource_ExposureStart)
        self._camera.CounterEventActivation.SetValue(PySpin.CounterEventActivation_RisingEdge)
        self._camera.CounterTriggerSource.SetValue(PySpin.CounterTriggerSource_ExposureStart)
        self._camera.CounterTriggerActivation.SetValue(PySpin.CounterTriggerActivation_RisingEdge)
        self._camera.LineSelector.SetValue(PySpin.LineSelector_Line2)
        self._camera.V3_3Enable.SetValue(True)
        self._camera.LineSelector.SetValue(PySpin.LineSelector_Line1)
        self._camera.LineSource.SetValue(PySpin.LineSource_Counter0Active)
        self._camera.LineInverter.SetValue(False)
        self._camera.TriggerMode.SetValue(PySpin.TriggerMode_Off)
        self._camera.TriggerSource.SetValue(PySpin.TriggerSource_Software)
        self._camera.TriggerOverlap.SetValue(PySpin.TriggerOverlap_Off)
        self._camera.TriggerMode.SetValue(PySpin.TriggerMode_On)

    def _configure_as_secondary(self):
        self._camera.TriggerSource.SetValue(PySpin.TriggerSource_Line3)
        self._camera.TriggerOverlap.SetValue(PySpin.TriggerOverlap_ReadOut)
        self._camera.TriggerActivation.SetValue(PySpin.TriggerActivation_AnyEdge)
        self._camera.TriggerMode.SetValue(PySpin.TriggerMode_On)

    def _set_bounded_int_property_node(self, prop_node, value: int) -> int:
        return int(self._set_bounded_property(prop_node, value))

    def _set_bounded_float_property_node(self, prop_node, value: float) -> float:
        return float(self._set_bounded_property(prop_node, value))

    def _set_bounded_property(self, prop_node, value):
        name = prop_node.GetDisplayName()
        if value is None:
            logger.warning("%s: received None value for _set_bounded_float_property_node", name)
            return 0
        set_value = value
        try:
            if prop_node.GetAccessMode() == PySpin.RW:
                max_width = prop_node.GetMax()
                if max_width is None:
                    set_value = value
                    logger.debug("%s: has no Max value", name)
                else:
                    set_value = min(max_width, value)
                prop_node.SetValue(set_value)
                set_value = prop_node.GetValue()
                logger.debug("%s: applied %s requested=%s (max=%s)", name, set_value, value, max_width)
            elif prop_node.GetAccessMode() == PySpin.RO:
                set_value = prop_node.GetValue()
                logger.error("%s GenApi is not writeable - current value is %s", name, set_value)
            else:
                logger.error("%s GenApi is not readable or writeable", name)
        except Exception as err:
            logger.error("%s: Exception during set: %s", name, err)
            raise

        return set_value

    def _set_bounded_bool_property_node(self, prop_node, value: bool) -> bool:
        set_value = value
        name = prop_node.GetDisplayName()
        try:
            if prop_node.GetAccessMode() == PySpin.RW:
                prop_node.SetValue(value)
                set_value = prop_node.GetValue()
                logger.debug("%s: set to %s ; requested %s", name, set_value, value)
            elif prop_node.GetAccessMode() == PySpin.RO:
                set_value = prop_node.GetValue()
                logger.warning(
                    "%s: GenApi is not writeable - current value is %s", name, set_value)
            else:
                logger.warning("%s: GenApi is not readable or writeable", name)
                set_value = None
        except Exception as err:
            logger.error("%s: Exception during set: %s", err)

        return set_value


atexit.register(lambda: _stop_spincam_lib_instance(SpinCam))
