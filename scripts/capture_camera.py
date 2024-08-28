import argparse
import logging
import os
import sys
from pathlib import Path
from queue import Queue
from datetime import datetime

import cv2

from autotrainer.core.project import ProjectInfo
from autotrainer.video import VideoManager, VideoRecordProperties
from autotrainer.video import VideoRecord

logging.basicConfig(level=logging.INFO)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


def capture_video(camera_url: str, video_path: str, frame_count: int):
    print("Camera URL:", camera_url)
    print("Video Path:", video_path)

    path = Path(video_path)
    path.mkdir(parents=True, exist_ok=True)

    file_timestamp = datetime.now()

    VideoManager.open()

    camera = VideoManager.create_camera(camera_url, "capture_camera")

    camera.prepare_capture()

    base_location = os.path.join(video_path)

    record_queue = Queue()
    record_project = ProjectInfo(base_location, "")
    record_properties = VideoRecordProperties(project_info=record_project, name="camera",
                                              video_rotate_interval=3600, frame_size=(camera.width, camera.height),
                                              image_interval=1, fps=camera.fps)
    record = VideoRecord(record_properties, record_queue)

    record.start()

    for idx in range(frame_count):
        image, when = camera.capture()

        if image is not None:
            cv2.imshow("window", image)
            cv2.waitKey(1)

            record_queue.put((image, when))

    camera.end_capture()

    record.cancel()

    VideoManager.close()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("cameraurl", help="the camera to use")
    parser.add_argument("output", help="the video file output location")
    parser.add_argument("-f", "--framecount", help="the number of frames to capture (default 30)",
                        type=int, default=30)

    args = parser.parse_args()

    capture_video(args.cameraurl, args.output, args.framecount)

    return True


if __name__ == '__main__':
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
