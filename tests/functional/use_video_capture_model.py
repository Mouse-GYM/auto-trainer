import argparse
import logging
import time

from tools.acquisition.model.video_capture_model import VideoCaptureModel

logging.basicConfig(level=logging.INFO)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logging.getLogger('tools').setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


def main(camera_url_1: str, camera_url_2: str, camera_url_3: str, iterations: int, duration: int, output_location: str):
    models = list()

    if camera_url_1 != "":
        model_1 = VideoCaptureModel("1")
        model_1.camera_source = camera_url_1
        model_1.set_display_fcn(lambda x, y: None)
        models.append(model_1)

    if camera_url_2 != "":
        model_2 = VideoCaptureModel("2")
        model_2.camera_source = camera_url_2
        model_2.set_display_fcn(lambda x, y: None)
        models.append(model_2)

    if camera_url_3 != "":
        model_3 = VideoCaptureModel("3")
        model_3.camera_source = camera_url_3
        model_3.set_display_fcn(lambda x, y: None)
        models.append(model_3)

    count = 0

    while count < iterations:
        logger.info("video capture process starting")

        success = True

        for model in models:
            res = model.on_prepare_capture(output_location)

            if not res:
                success = False
                logger.error(f"video capture model failed to prepare: {model.camera_source}")
                break

        if success is True:
            for model in models:
                model.on_capture_start()

            time.sleep(duration)

        for model in models:
            model.on_capture_stop()

        count += 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("-l", "--left", help="camera 1")
    parser.add_argument("-r", "--right", help="camera 2")
    parser.add_argument("-t", "--top", help="camera 3")
    parser.add_argument("-i", "--iterations", help="the number of process iterations (default 10)", type=int,
                        default=10)
    parser.add_argument("-d", "--duration", help="the capture duration in seconds for each iteration (default 2)",
                        type=int, default=2)
    parser.add_argument("-o", "--output", help="the output location for recorded files")

    args = parser.parse_args()

    main(args.left, args.right, args.top, args.iterations, args.duration, args.output)
