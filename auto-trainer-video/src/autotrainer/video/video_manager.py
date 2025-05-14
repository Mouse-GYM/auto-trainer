import sys
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

import cv2

from autotrainer.core.logging import get_verbose_logger

from .camera.camera_base import CameraBase
from .camera.random_cam import RandomCam
from .camera.playback_cam import PlaybackCam
from .camera.opencv_cam import OpenCVCam

logger = get_verbose_logger(__name__)

_have_spin_cam = False

if sys.version_info.major == 3 and sys.version_info.minor == 8 and not sys.platform.startswith("darwin"):
    try:
        from .camera.spinnaker_cam import SpinCam
        _have_spin_cam = True
    except Exception as err:
        logger.debug("Cannot import SpinCam: %s, but continuing", err)


class CameraKind(str, Enum):
    Random = "random"
    Playback = "playback"
    Spinnaker = "spinnaker"
    OpenCV = "opencv"


class VideoManager:
    @classmethod
    def open(cls):
        if _have_spin_cam:
            SpinCam.start()

    @classmethod
    def close(cls):
        if _have_spin_cam:
            SpinCam.stop()

    @classmethod
    def list_usb_cameras(cls) -> list:
        cameras = list()

        for idx in range(6):
            capture = cv2.VideoCapture(idx)
            if capture.isOpened():
                ret, frame = capture.read()
                if ret and frame is not None:
                    cameras.append(idx)

        return cameras

    @classmethod
    def list_spin_cameras(cls) -> list:
        if _have_spin_cam:
            return SpinCam.list()
        else:
            return list()

    @classmethod
    def get_spin_camera(cls, serial_number: str, name: str = ""):
        if _have_spin_cam:
            return SpinCam.create(serial_number, name)
        else:
            return None

    @classmethod
    def parse_params(cls, camera_url: str) -> dict:
        parameters = dict()

        parsed = urlparse(camera_url)

        params = parsed.query.split("&")

        for param in params:
            values = param.split("=")
            if len(values) == 2:
                parameters[values[0].lower()] = values[1]

        return parameters

    @classmethod
    def create_camera(cls, camera_url: str, name: str = "") -> Optional[CameraBase]:
        parsed = urlparse(camera_url)

        if parsed.scheme == CameraKind.Random:
            camera = RandomCam(name)
        elif parsed.scheme == CameraKind.Spinnaker:
            camera = cls.get_spin_camera(parsed.hostname, name)
        elif parsed.scheme == CameraKind.Playback:
            camera = PlaybackCam(parsed.path, name)
        elif parsed.scheme == CameraKind.OpenCV:
            camera = OpenCVCam(int(parsed.hostname), name)
        else:
            logger.warning("No such cam scheme: %s", parsed.scheme)
            return None

        camera.init()

        params = parsed.query.split("&")

        for param in params:
            values = param.split("=")
            if len(values) == 2:
                camera.set_property(values[0], values[1])

        return camera
