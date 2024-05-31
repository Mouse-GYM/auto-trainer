import argparse
import sys

from autotrainer.video import VideoManager


def acquire_image(camera_url: str):
    print("Camera URL:", camera_url)

    VideoManager.open()

    camera = VideoManager.create_camera(camera_url)

    camera.prepare_capture()

    camera.capture()

    camera.end_capture()

    print("image captured")

    VideoManager.close()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("cameraurl", help="the camera to use")

    args = parser.parse_args()
    acquire_image(args.cameraurl)

    return True


if __name__ == '__main__':
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
