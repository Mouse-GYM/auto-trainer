import argparse
import logging
import os
from multiprocessing import set_start_method

import pytest

logging.basicConfig(level=logging.WARNING)
logging.getLogger("autotrainer").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


# TODO NOT READY

def prepare_video_capture(file_name):
    import cv2

    if os.path.isfile(file_name):
        capture = cv2.VideoCapture(file_name)
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        return capture, frame_count

    return None, 0


@pytest.mark.skip(reason="Not implemented")
def test_dlc_load(network, _left_source, _right_source, batch_size):
    from autotrainer.inference import DlcPoseModel

    # left_capture, front_frame_count = prepare_video_capture(left_source)

    # right_capture, side_frame_count = prepare_video_capture(right_source)

    configuration = DlcPoseModel(network, 1, 0, batch_size * 2)

    configuration.load()


if __name__ == '__main__':
    set_start_method("spawn")

    parser = argparse.ArgumentParser()

    parser.add_argument("inference", help="the DeepLabCut inference to use")
    parser.add_argument("left", help="the left camera video source file")
    parser.add_argument("right", help="the right camera video source file")
    parser.add_argument("-b", "--batchsize", help="the batch size for DLC", type=int, default=5)

    args = parser.parse_args()

    if not os.path.exists(os.path.join(args.inference, "config.yaml")):
        logger.error("The inference configuration does not exist")

    if not os.path.exists(args.left):
        logger.error("The left camera video file does not exist")

    if not os.path.exists(args.right):
        logger.error("The right camera video file does not exist")

    test_dlc_load(args.inference, args.left, args.right, args.batchsize)
