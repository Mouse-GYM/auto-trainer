import logging
import sys
import os
import argparse
import time

from cProfile import Profile
from pstats import SortKey, Stats

import cv2
import numpy

from autotrainer.dlc.dlc_configuration import DLCConfiguration

logging.basicConfig(level=logging.INFO)
logging.getLogger("root").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def prepare_video_capture(file_name):
    if os.path.isfile(file_name):
        capture = cv2.VideoCapture(file_name)
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        return capture, frame_count

    return None, 0


def process_video(network, front_source, side_source, batch_size: int, user_max_frames: int, report_profile: bool):
    front_capture, front_frame_count = prepare_video_capture(front_source)

    side_capture, side_frame_count = prepare_video_capture(side_source)

    max_frames = int(min(front_frame_count, side_frame_count))

    configuration = DLCConfiguration()

    configuration.load_configuration(os.path.join(network, "config.yaml"), 1, 0, batch_size * 2)

    idx = 0

    frames = numpy.ndarray((batch_size * 2, 200, 300, 3))

    frame_count = 0

    start_time = time.perf_counter()

    if user_max_frames > 0:
        max_frames = min(max_frames, user_max_frames)

    with Profile() as profile:
        while True:
            for fdx in range(batch_size):
                if idx >= max_frames:
                    break

                ret1, front_frame = front_capture.read()
                ret2, side_frame = side_capture.read()

                frames[fdx * 2, :, :, :] = front_frame
                frames[fdx * 2 + 1, :, :, :] = side_frame

                idx += 1

            pose = configuration.predict(frames)

            frame_count += batch_size

            if frame_count % 100 == 0:
                print(f"{(frame_count / (time.perf_counter() - start_time)):.1f} Network FPS")

            if idx >= max_frames:
                break

        if report_profile:
            Stats(profile).strip_dirs().sort_stats(SortKey.TIME).print_stats()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("network", help="the DeepLabCut network to use")
    parser.add_argument("front", help="the front camera video source file")
    parser.add_argument("side", help="the side camera video source file")
    parser.add_argument("-b", "--batchsize", help="the number of frames to toggle", type=int, default=5)
    parser.add_argument("-f", "--frames", help="the number of frames to toggle", type=int, default=-1)
    parser.add_argument("-p", "--profile", help="report profiling data", type=bool, default=False)

    args = parser.parse_args()

    if not os.path.exists(args.front):
        logger.error("The front/left camera video file does not exist")

    if not os.path.exists(args.side):
        logger.error("The side/right camera video file does not exist")

    process_video(args.network, args.front, args.side, args.batchsize, args.frames, args.profile)

    return True


if __name__ == '__main__':
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
