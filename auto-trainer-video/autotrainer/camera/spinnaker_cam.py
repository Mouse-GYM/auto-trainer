import logging
from enum import Enum

import PySpin
import numpy

from .camera_base import CameraBase

logger = logging.getLogger(__name__)


class AcquisitionMode(Enum):
    Continuous = 0
    SingleFrame = 1
    MultiFrame = 2


class SpinCam(CameraBase):
    _sSystem = None

    _cameras = dict()

    @classmethod
    def start(cls):
        if cls._sSystem is None:
            cls._sSystem = PySpin.System.GetInstance()

    @classmethod
    def stop(cls):
        for key in cls._cameras:
            cls._cameras[key].__release()

        if cls._sSystem is not None:
            cls._sSystem.ReleaseInstance()

    @classmethod
    def list(cls):
        serial_numbers = list()

        cam_list = cls._sSystem.GetCameras()

        for i, cam in enumerate(cam_list):
            serial_numbers.append(cam.TLDevice.DeviceSerialNumber.ToString())

        cam_list.Clear()

        return serial_numbers

    @classmethod
    def create(cls, serial_number: str, name: str = ""):
        if serial_number in cls._cameras:
            return cls._cameras[serial_number]
        else:
            cam_list = cls._sSystem.GetCameras()

            camera = cam_list.GetBySerial(serial_number)

            obj = SpinCam(name)
            obj.__create(camera)

            cls._cameras[serial_number] = obj

            cam_list.Clear()

            return obj

    _camera = None
    _node_map = None
    _node_map_tl_device = None

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._width = 1440
        self._height = 1080

        self._fps = 150
        self._horizontal_binning = 1
        self._vertical_binning = 1
        self._exposure = 5000
        self._offset_x = 0
        self._offset_y = 0

        self._is_secondary = False

        self._pause_log = False

    def __create(self, camera):
        self._camera = camera

        self._image_processor = PySpin.ImageProcessor()
        self._image_processor.SetColorProcessing(PySpin.SPINNAKER_COLOR_PROCESSING_ALGORITHM_HQ_LINEAR)

    def __release(self):
        self._camera.DeInit()

        del self._camera

    @property
    def fps(self) -> float:
        return self._fps

    @fps.setter
    def fps(self, value: float) -> None:
        self._camera.AcquisitionFrameRateEnable.SetValue(True)
        self._camera.AcquisitionFrameRate.SetValue(value)
        self._fps = value

        if not self._pause_log:
            logger.debug(f"<{self._name}> fps: {self._fps}")

    @property
    def width(self):
        return self._width

    @width.setter
    def width(self, value):
        self._width = self._set_bounded_int_property_node(self._camera.Width, value)

    @property
    def height(self):
        return self._height

    @height.setter
    def height(self, value):
        self._height = self._set_bounded_int_property_node(self._camera.Height, value)

    @property
    def offset_x(self):
        return self._offset_x

    @offset_x.setter
    def offset_x(self, value):
        self._offset_x = self._set_bounded_int_property_node(self._camera.OffsetX, value)

    @property
    def offset_y(self):
        return self._offset_y

    @offset_y.setter
    def offset_y(self, value):
        self._offset_y = self._set_bounded_int_property_node(self._camera.OffsetY, value)

    @property
    def horizontal_binning(self) -> int:
        return self._horizontal_binning

    @horizontal_binning.setter
    def horizontal_binning(self, value: int) -> None:
        self._horizontal_binning = self._set_bounded_int_property_node(self._camera.BinningHorizontal, value)

    @property
    def vertical_binning(self) -> int:
        return self._vertical_binning

    @vertical_binning.setter
    def vertical_binning(self, value: int) -> None:
        self._vertical_binning = self._set_bounded_int_property_node(self._camera.BinningVertical, value)

    @property
    def exposure(self) -> int:
        return self._exposure

    @exposure.setter
    def exposure(self, value: int) -> None:
        self._exposure = self._set_bounded_int_property_node(self._camera.ExposureTime, value)

    def init(self):
        self._camera.Init()

        self._node_map = self._camera.GetNodeMap()

        if self._camera.Width.GetAccessMode() != PySpin.RW:
            # Stackflow 64660434.  Apparently there is no simple reset/release call to fix when it is in this state.
            self._camera.BeginAcquisition()
            self._camera.EndAcquisition()
            self._camera.DeInit()
            self._camera.Init()

        node_acquisition_mode = PySpin.CEnumerationPtr(self._node_map.GetNode('AcquisitionMode'))

        node_acquisition_mode.SetIntValue(AcquisitionMode.Continuous.value)

        if self._camera.ExposureAuto.GetAccessMode() == PySpin.RW:
            self._camera.ExposureAuto.SetValue(PySpin.ExposureAuto_Off)
            logger.debug(f"<{self._name}> ExposureAuto set to {self._camera.ExposureAuto.GetValue()}")
        else:
            logger.warning(f"<{self._name} ExposureAuto is not writeable")

        if self._camera.GainAuto.GetAccessMode() == PySpin.RW:
            self._camera.GainAuto.SetValue(PySpin.GainAuto_Off)
            logger.debug(f"<{self._name}> GainAuto set to {self._camera.GainAuto.GetValue()}")
        else:
            logger.warning(f"<{self._name} GainAuto is not writeable")

        if self._camera.Gain.GetAccessMode() == PySpin.RW:
            self._camera.Gain.SetValue(0)
            logger.debug(f"<{self._name}> Gain set to {self._camera.Gain.GetValue()}")
        else:
            logger.warning(f"<{self._name} Gain is not writeable")

        self._pause_log = True


        # Set to class defaults.  Camera URL may override later.
        self.offset_x = self._offset_x
        self.offset_y = self._offset_y
        self.horizontal_binning = self._horizontal_binning
        self.vertical_binning = self._vertical_binning
        self.exposure = self._exposure
        self.fps = self._fps

        self.width = self.width
        self.height = self.height

        self._pause_log = False

    def prepare_capture(self):
        super().prepare_capture()

        if self._is_primary:
            self._configure_as_primary()
            logger.info(f"<{self.name}> configured as primary")
        elif self._is_secondary:
            self._configure_as_secondary()
            logger.info(f"<{self.name}> configured as secondary")

        self._camera.BeginAcquisition()

    def end_capture(self):
        super().end_capture()

        self._camera.EndAcquisition()

        if self._is_primary:
            self._camera.LineSelector.SetValue(PySpin.LineSelector_Line1)
            self._camera.LineSource.SetValue(PySpin.LineSource_FrameTriggerWait)
            self._camera.LineInverter.SetValue(True)
        elif self._is_secondary:
            self._camera.TriggerMode.SetValue(PySpin.TriggerMode_Off)

    def capture(self) -> (numpy.ndarray, int):
        image_result = self._camera.GetNextImage()

        image_converted = self._image_processor.Convert(image_result, PySpin.PixelFormat_Mono8)

        frame = numpy.zeros([self._height, self._width], "ubyte")

        frame[:, :] = image_converted.GetNDArray()

        self._last_when = image_result.GetTimeStamp()

        if self._frame_count == 0:
            self._acquisition_start = self._last_when

        self._frame_count += 1

        image_result.Release()

        return frame, self._last_when

    def set_property(self, name: str, value: str) -> bool:
        if name == "primary":
            self._is_primary = bool(value)
        elif name == "secondary":
            self._is_secondary = bool(value)
        elif name == "offsetx":
            self.offset_x = int(value)
        elif name == "offsety":
            self.offset_y = int(value)
        elif name == "hbin":
            self.horizontal_binning = int(value)
        elif name == "vbin":
            self.vertical_binning = int(value)
        elif name == "exposure":
            self.exposure = int(value)
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

        self._camera.LineSelector.SetValue(PySpin.LineSelector_Line1)
        self._camera.LineSource.SetValue(PySpin.LineSource_Counter0Active)
        self._camera.TriggerMode.SetValue(PySpin.TriggerMode_Off)

    def _configure_as_secondary(self):
        self._camera.TriggerSource.SetValue(PySpin.TriggerSource_Line3)
        self._camera.TriggerOverlap.SetValue(PySpin.TriggerOverlap_ReadOut)
        self._camera.TriggerActivation.SetValue(PySpin.TriggerActivation_AnyEdge)
        self._camera.TriggerMode.SetValue(PySpin.TriggerMode_On)

    def _set_bounded_int_property_node(self, prop_node, value: int) -> int:
        set_value = value

        try:
            if prop_node.GetAccessMode() == PySpin.RW:
                max_width = prop_node.GetMax()
                set_value = min(max_width, value)
                prop_node.SetValue(value)
                set_value = prop_node.GetValue()
                if not self._pause_log:
                    logger.debug(f"<{self._name}> {prop_node.GetDisplayName()} set to {set_value}")
            elif prop_node.GetAccessMode() == PySpin.RO:
                set_value = prop_node.GetValue()
                logger.warning(
                    f"<{self._name}> {prop_node.GetDisplayName()} GenApi is not writeable - current value is {set_value}")
            else:
                logger.warning(f"<{self._name}> {prop_node.GetDisplayName()} GenApi is not readable or writeable")
        except Exception as ex:
            logger.error(f"<{self._name}> {prop_node.GetDisplayName()} Exception during set {ex}")

        return set_value
