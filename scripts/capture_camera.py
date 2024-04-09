import argparse
import logging
import os
import sys
from queue import Queue

import cv2
from autotrainer.video_manager import VideoManager
from autotrainer.video_record import VideoRecord

logging.basicConfig(level=logging.INFO)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


def capture_video(camera_url: str, video_path: str):
    print("Camera URL:", camera_url)
    print("Video Path:", video_path)

    VideoManager.open()

    camera = VideoManager.create_camera(camera_url)

    camera.prepare_capture()

    record_queue = Queue()
    record = VideoRecord(video_path, "camera", 3600, (camera.width, camera.height), 30, record_queue)
    record.start()

    for idx in range(150):
        image = camera.capture()
        cv2.imshow("window", image)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        record_queue.put(image)

    camera.end_capture()

    record.cancel()

    VideoManager.close()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("cameraurl", help="the camera to use")
    parser.add_argument("output", help="the video file output location")

    args = parser.parse_args()
    print(os.environ.get('PATH'))
    capture_video(args.cameraurl, args.output)

    return True


if __name__ == '__main__':
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
