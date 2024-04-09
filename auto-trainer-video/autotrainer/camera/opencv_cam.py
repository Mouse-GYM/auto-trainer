import cv2


from . camera_base import CameraBase


class OpenCVCam(CameraBase):
    def __init__(self, device_idx: int):
        super().__init__()
        self._device_idx = device_idx
        self._video_capture = None

    def init(self):
        self._video_capture = cv2.VideoCapture(self._device_idx)

        self.width = int(self._video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self._video_capture.get(cv2.CAP_PROP_FPS)

    def end_capture(self):
        super().end_capture()
        
        self._video_capture.release()

    def capture(self):
        super().capture()

        ret, frame = self._video_capture.read()

        frame = frame[:, :, 0]

        return frame
