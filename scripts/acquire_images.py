from autotrainer.video_manager import VideoManager

VideoManager.open()

cameras = VideoManager.list_spin_cameras()

print("using camera {}".format(cameras[0]))

camera = VideoManager.get_spin_camera(cameras[0])

camera.init()

camera.prepare_capture()

camera.capture()

camera.end_capture()

print("image captured")

VideoManager.close()
