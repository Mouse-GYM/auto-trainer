from autotrainer.video_manager import VideoManager

VideoManager.open()

cameras = VideoManager.list_spin_cameras()

if len(cameras) == 0:
    print("No cameras")
else:
    for i, sn in enumerate(cameras):
        print("Camera {}: {}".format(i, sn))

    camera = VideoManager.get_spin_camera(cameras[0])

VideoManager.close()
