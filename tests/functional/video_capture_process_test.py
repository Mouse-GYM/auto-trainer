import argparse
import logging
import time
from multiprocessing import Queue

from autotrainer.video_capture import VideoCapture, CaptureMessageKind
from autotrainer.queue_util import clear_queue

logging.basicConfig(level=logging.INFO)
logging.getLogger('autotrainer').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def main(camera_url: str, iterations: int, duration: int):
    cmd_queue = Queue()
    status_queue = Queue()
    image_queue = Queue()

    count = 0

    while count < iterations:
        logger.info("video capture process starting")

        process = VideoCapture("A", cmd_queue, status_queue, image_queue, None, camera_url, None)

        process.start()

        retry_count = 0

        while True:
            try:
                status_queue.get(timeout=5)
                break
            except:
                retry_count += 1
                logger.warning(f"ready acknowledgement not received ({retry_count} attempts)")

        cmd_queue.put(CaptureMessageKind.BEGIN_CAPTURE)

        time.sleep(duration)

        cmd_queue.put(CaptureMessageKind.END_CAPTURE)

        time.sleep(0.25)

        cmd_queue.put(CaptureMessageKind.TERMINATE)

        status_queue.get()

        clear_queue(image_queue)

        time.sleep(0.5)

        while process.is_alive():
            logger.warning("still alive...")
            time.sleep(0.5)

        logger.info("process fully terminated")

        count += 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("cameraurl", help="the camera to use")
    parser.add_argument("-i", "--iterations", help="the number of process iterations (default 10)", type=int,
                        default=10)
    parser.add_argument("-d", "--duration", help="the capture duration in seconds for each iteration (default 2)",
                        type=int, default=2)

    args = parser.parse_args()

    main(args.cameraurl, args.iterations, args.duration)
