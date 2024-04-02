import os

# Must precede import cv2
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"

from autotrainer.video_manager import VideoManager

VideoManager.open()

print("Random Image Generator")
print("\tCamera 0: random://0")

usb_cameras = VideoManager.list_usb_cameras()
print("USB Cameras")

if len(usb_cameras) == 0:
    print("\tNo cameras")
else:
    for i, sn in enumerate(usb_cameras):
        print(f"\tCamera {i}: opencv://{sn}")

flir_cameras = VideoManager.list_spin_cameras()

print("FLIR/Spinnaker")

if len(flir_cameras) == 0:
    print("\tNo cameras")
else:
    for i, sn in enumerate(flir_cameras):
        print(f"\tCamera {i}: spinnaker://{sn}")

print("File Playback")
print("\tCamera X: playback://<path_to_file>")

VideoManager.close()
