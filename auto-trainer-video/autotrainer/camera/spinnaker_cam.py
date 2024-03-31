import logging
from enum import Enum

import PySpin
import numpy

from . camera_base import CameraBase

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
    def create(cls, serial_number: str):
        if serial_number in cls._cameras:
            return cls._cameras[serial_number]
        else:
            cam_list = cls._sSystem.GetCameras()

            camera = cam_list.GetBySerial(serial_number)

            obj = SpinCam()
            obj.__create(camera)

            cls._cameras[serial_number] = obj

            cam_list.Clear()

            return obj

    _camera = None
    _node_map = None
    _node_map_tl_device = None

    def __init__(self):
        super().__init__()
        self._width = 1440
        self._height = 1080

    def __create(self, camera):
        self._camera = camera

        self._image_processor = PySpin.ImageProcessor()
        self._image_processor.SetColorProcessing(PySpin.SPINNAKER_COLOR_PROCESSING_ALGORITHM_HQ_LINEAR)

    def __release(self):
        self._camera.DeInit()

        del self._camera

    @property
    def width(self):
        return self._width

    @width.setter
    def width(self, value):
        node_width = PySpin.CIntegerPtr(self._node_map.GetNode('Width'))

        if PySpin.IsAvailable(node_width) and PySpin.IsWritable(node_width):
            max_width = node_width.GetMax()
            node_width.SetValue(min(max_width, value))
            self._width = min(max_width, value)
            logger.debug(f"width set to {self._width}")
        else:
            logger.warning("width node not available")

    @property
    def height(self):
        return self._height

    @height.setter
    def height(self, value):
        node_height = PySpin.CIntegerPtr(self._node_map.GetNode('Height'))

        if PySpin.IsAvailable(node_height) and PySpin.IsWritable(node_height):
            max_height = node_height.GetMax()
            node_height.SetValue(min(max_height, value))
            self._height = min(max_height, value)
            logger.debug(f"height set to {self._height}")
        else:
            logger.warning("height node not available")

    def init(self):
        self._camera.Init()

        self._node_map = self._camera.GetNodeMap()

        node_acquisition_mode = PySpin.CEnumerationPtr(self._node_map.GetNode('AcquisitionMode'))

        node_acquisition_mode.SetIntValue(AcquisitionMode.Continuous.value)

        if self._camera.BinningHorizontal.GetAccessMode() == PySpin.RW:
            self._camera.BinningHorizontal.SetValue(4)

        if self._camera.BinningVertical.GetAccessMode() == PySpin.RW:
            self._camera.BinningVertical.SetValue(4)

        if self._camera.ExposureAuto.GetAccessMode() == PySpin.RW:
            self._camera.ExposureAuto.SetValue(PySpin.ExposureAuto_Off)
            self._camera.ExposureTime.SetValue(5000)

        self._camera.AcquisitionFrameRateEnable.SetValue(True)
        self._camera.AcquisitionFrameRate.SetValue(150)
        self.fps = 150.00

        self._width = self._camera.Width.GetValue()
        self._height = self._camera.Height.GetValue()

    def prepare_capture(self):
        self._camera.BeginAcquisition()

    def end_capture(self):
        self._camera.EndAcquisition()

    def capture(self):
        image_result = self._camera.GetNextImage()

        image_converted = self._image_processor.Convert(image_result, PySpin.PixelFormat_Mono8)

        frame = numpy.zeros([self._height, self._width], "ubyte")

        frame[:, :] = image_converted.GetNDArray()

        image_result.Release()

        return frame
