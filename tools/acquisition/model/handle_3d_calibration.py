
import os.path
import collections
import time
import dataclasses
from typing import Dict, Any, Optional, List
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from autotrainer.core import Offset3DTuple, get_verbose_logger
from autotrainer.core.analysis import calibration_FLIR
from autotrainer.pyside.content_widget import InvokeMethod
from autotrainer.video import VideoRecordMode, CaptureProcessStatus

from tools.acquisition.model.app_model import AppModel


logger = get_verbose_logger(__name__)

x, y, z = 'xyz'

start = (
    (x, -9.4),
    (y, 10.0),
    (z, -35.0),
)

moves = [
    (z, -30.0),
    (x, -5.0),
    (y, 15.0),
    (z, -35.0),
    (x, -1.0),
    (z, -27.0),
    (x, -9.0),
    (y, 20.0),
    (z, -35.0),
    (x, 0.0),
    (z, -25.0),
    (y, 25.0),
    (x, -9.0),
    (z, -35.0),
    (z, -30.0),
    (x, 5.0),
    (z, -25.0),
    (y, 30.0),
    (x, -7.0),
    (z, -35.0),
    (z, -27.0),
    (y, 35.0),
    (x, 10.0),
    (z, -22.0),
    (x, -5.0),
    # move through center:
    (z, -27.0),
    (x, -3.0),
    (y, 30.0),
    (z, -30.0),
    (x, -5.0),
    (y, 25.0),
    (z, -30.0),
    (x, -9.0),
    (y, 20.0),
    (z, -35.0),
    (y, 15.0),
]

# start = [
#     (x, -11.7),
#     (y, 38.5),
#     (z, -1.9),
# ]
#
#
# moves = [
#     (x, 0),
#     (z, -4),
#     (x, -11.7),
#     (z, -1.9),
# ]


default_params = dict(
    vbin=1,
    hbin=1,
    width=1440,
    height=1080,
    exposure=1500,
    fps=30,
    # primary=cam is left,
    offsetx=0,
    offsety=0,
    # gain=1,
    # gamma: 0.7
)


def process_capture(src_dir):
    # Can be set to false while refining other variables
    calibrate = True
    # Of no consequence??
    alpha = 1
    # Threshold for qutomatic corner-finding quality assessment, between 0 and 1
    quality = 0.95
    # Gamma correction can improve chessboard corner finding
    gamma = 1
    # Number of frames to extract
    num_frames = 100
    # Prepare for out-of-plane camera correction
    camera_pos = {
        'camLele': 12.5,
        'camRele': 30,
        'camLazi': -55,
        'camRazi': -5,
    }
    calibration_FLIR.create_corner_matrix(
        src_dir,
        num_frames=num_frames,
        gamma=gamma,
        camera_pos=camera_pos,
        alpha=alpha,
        quality=quality,
        calibrate=calibrate,
    )


def make_3d_calib(
    app_model: AppModel,
    cam_params: Optional[Dict[str, Any]] = None,
):
    if cam_params is None:
        cam_params = default_params
    left = app_model.left_camera
    right = app_model.right_camera
    cams = (left, right)
    cams_before_cfg = tuple(cam.save_configuration() for cam in cams)
    hard = app_model.hardware
    diamond_triangle_cfg = app_model.behavior.algorithm.diamond_triangle_config
    if diamond_triangle_cfg is None:
        raise RuntimeError(f"Please first calibrate diamond-triangle by starting the acquisition")
    d_to_m = diamond_triangle_cfg.diamond_to_motor
    def m_x(v):
        return hard.move_x(d_to_m(Offset3DTuple(v, 0, 0)).x)
    def m_y(v):
        return hard.move_y(d_to_m(Offset3DTuple(0, v, 0)).y)
    def m_z(v):
        return hard.move_z(d_to_m(Offset3DTuple(0, 0, v)).z)
    coord2m = {
        x: m_x,
        y: m_y,
        z: m_z,
    }
    #
    project = app_model.make_project_info()
    project.calculate_next_session_index()
    #
    sess_path = project.get_session_path()
    #
    square_size = 4  # in millimeters
    row_ct = 6
    col_ct = 8
    # If the frames were sampled at a higher resolution than will be used for
    # normal acquisition, this is the x-fold oversampling factor
    oversample = 4
    src_dir = Path(
        calibration_FLIR.make_new_calibration(square_size, row_ct, col_ct, oversample, sess_path.location))

    def wait_cams_capture_status(capture_status: CaptureProcessStatus, timeout: float):
        p_before = time.perf_counter()
        p_timeout = p_before + timeout
        for cam in cams:
            while (cur_status := cam.capture_process_status) != capture_status:
                if time.perf_counter() > p_timeout:
                    raise RuntimeError(f"Timeout waiting capture status {capture_status} on cam {cam.name}"
                                       f" ; current={cur_status}")
                time.sleep(0.001)
            logger.info("%s: got %s", cam.name, capture_status)

    def prepare():
        # app_model.on_capture_start
        logger.notice("Preparing ..")
        logger.info("Connecting to HW ..")
        hard.connect(app_model.message_handler.input_queue)
        token = hard.send_home()
        hard.wait_pending_command_acked(token, timeout=60)
        #
        for cam, cfg in zip(cams, cams_before_cfg):
            logger.info("Preparing cam %s", cam.name)
            params = cam_params.copy()
            params["primary"] = cam is left
            new_cfg = dataclasses.replace(
                cfg,
                record_mode=VideoRecordMode.TRIGGER.value,
                record_prebuffer_duration=0,
                is_enabled=True,
                is_record_enabled=True,
                params=params,
            )
            cam.load_configuration(new_cfg)
            cam.project = project
            logger.info("%s: prepare capture ..", cam.name)
            cam.on_prepare_capture()

        for cam in cams:
            logger.info("%s: capture start ..", cam.name)
            cam.on_capture_start()

        # wait_cams_capture_status(CaptureProcessStatus.RUNNING, 5)  # already done by on_prepare_capture()

    def run():
        logger.notice("Running 3d calib ..")

        logger.verbose("Setting start position")
        key = None
        for coord, value in start:
            key = coord2m[coord](value)
        hard.wait_pending_command_acked(key)

        max_requests = 1
        cur_requests = collections.deque(maxlen=max_requests)
        #
        logger.info("Trigering recording")
        for cam in cams:
            cam.on_trigger_recording(True)
        #
        logger.notice("Waiting RECORDING on cams")
        wait_cams_capture_status(CaptureProcessStatus.RECORDING, 5)

        logger.info("Now executing calib moves ..")

        for coord, value in moves:
            if len(cur_requests) >= max_requests:
                hard.wait_pending_command_acked(cur_requests.popleft())
            logger.verbose("coord-%s -> %s", coord, value)
            key = coord2m[coord](value)
            cur_requests.append(key)
        while len(cur_requests) > 0:
            hard.wait_pending_command_acked(cur_requests.popleft())

        logger.info("Requesting cameras stop recording")

        for cam in reversed(cams):
            cam.on_trigger_recording(False)

        logger.success("executed %s moves", len(moves))

        wait_cams_capture_status(CaptureProcessStatus.RUNNING, 15)

    try:
        prepare()
        run()
    except Exception as err:
        logger.exception("Could not prepare and run 3d calib: %s", err)
        failed = err
    else:
        failed = None
    finally:
        for cam in reversed(cams):
            logger.info("%s: notify end cam", cam.name)
            cam.on_capture_notify_end()
        for cam in reversed(cams):
            logger.info("%s: stopping cam", cam.name)
            cam.on_capture_stop()
        hard.disconnect()
        wait_cams_capture_status(CaptureProcessStatus.TERMINATED, 5)
        logger.verbose("Resetting cams to previous config")
        for cam, cam_cfg in zip(cams, cams_before_cfg):
            cam.load_configuration(cam_cfg)

    if failed is None:
        for cam in cams:
            vp = Path(project.get_video_path(cam.name, allow_overwrite=True)[0])
            target = src_dir.joinpath(f"source_videos/{cam.name}.mp4")
            logger.verbose("%s -> %s", vp.as_posix(), target.as_posix())
            vp.rename(target)
        process_capture(src_dir.as_posix())

    logger.success("Successfully processed capture")
