import sys
import os
import argparse
import time

from cProfile import Profile
from pstats import SortKey, Stats

import cv2
import numpy

from autotrainer.dlc.dlc_configuration import DLCConfiguration


def prepare_video_capture(file_name):
    if os.path.isfile(file_name):
        capture = cv2.VideoCapture(file_name)
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        return capture, frame_count

    return None, 0


def process_video(network, front_source, side_source):
    front_capture, front_frame_count = prepare_video_capture(front_source)

    side_capture, side_frame_count = prepare_video_capture(side_source)

    max_frames = int(min(front_frame_count, side_frame_count))

    configuration = DLCConfiguration()

    configuration.load_configuration(os.path.join(network, "config.yaml"), 1, 0, 10)

    idx = 0

    frames = numpy.ndarray((10, 200, 300, 3))

    frame_count = 0

    start_time = time.perf_counter()

    max_frames = min(max_frames, 200)

    with Profile() as profile:
        while True:
            for fdx in range(5):
                if idx >= max_frames:
                    break

                ret1, front_frame = front_capture.read()
                ret2, side_frame = side_capture.read()

                frames[fdx * 2, :, :, :] = front_frame
                frames[fdx * 2 + 1, :, :, :] = side_frame

                idx += 1

            pose = configuration.predict(frames)

            frame_count += 5

            if frame_count % 100 == 0:
                print(f"{(frame_count / (time.perf_counter() - start_time)):.1f}")

            if idx >= max_frames:
                break

        Stats(profile).strip_dirs().sort_stats(SortKey.TIME).print_stats()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("network", help="the DeepLabCut network to use")
    parser.add_argument("front", help="the front camera video source file")
    parser.add_argument("side", help="the side camera video source file")

    args = parser.parse_args()

    process_video(args.network, args.front, args.side)

    return True


if __name__ == '__main__':
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
