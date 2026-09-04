import collections
import time
import dataclasses
from typing import Dict, Any, Optional, List
from pathlib import Path

from autotrainer.core import Offset3DTuple, get_verbose_logger, ProjectInterval
from autotrainer.inference import calibration_FLIR
from autotrainer.pyside.content_widget import InvokeMethod
from autotrainer.video import VideoRecordMode
from autotrainer.core.capture import CaptureProcessStatus

from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.video_capture_model import VideoCaptureModel

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
    exposure=4500,
    fps=40,
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
    quality = 0.925
    # Gamma correction can improve chessboard corner finding
    gamma = 2
    # Number of frames to extract
    num_frames = None
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
    record_mode: VideoRecordMode = VideoRecordMode.START_CONTINUOUS,
) -> Path:
    if cam_params is None:
        cam_params = default_params
    left = app_model.left_camera
    right = app_model.right_camera
    cameras: List[VideoCaptureModel] = []
    # put primary first:
    for camera in (left, right):
        if camera.is_primary:
            cameras.insert(0, camera)
        else:
            cameras.append(camera)
    cams_before_cfg = tuple(camera.save_configuration() for camera in cameras)
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
    project.calculate_next_trial_index()
    #
    sess_path = project.get_trial_path()
    #
    square_size = 4  # in millimeters
    row_ct = 6
    col_ct = 8
    # If the frames were sampled at a higher resolution than will be used for
    # normal acquisition, this is the x-fold oversampling factor
    oversample = 4
    src_dir = Path(
        calibration_FLIR.make_new_calibration(square_size, row_ct, col_ct, oversample, sess_path.location))

    def wait_cams_capture_status(capture_status: CaptureProcessStatus, timeout: float = 3):
        p_before = time.perf_counter()
        p_timeout = p_before + timeout
        for cam in cameras:
            cam.wait_for_capture_status(capture_status, timeout=p_timeout - time.perf_counter())
            logger.info("%s: got %s", cam.name, capture_status)

    def prepare():
        logger.notice("Preparing ..")
        #
        logger.info("Connecting to HW ..")
        hard.connect(app_model.message_handler.input_queue)
        tokens = set()
        with hard.wait_pending_command_acked(tokens):
            token = hard.send_home()
            tokens.add(token)
        #
        logger.verbose("Setting start position")
        tokens.clear()
        with hard.wait_pending_command_acked(tokens):
            for coord, value in start:
                key = coord2m[coord](value)
                tokens.add(key)
        #
        for cam, cfg in zip(cameras, cams_before_cfg):
            params = cam_params.copy()
            params["primary"] = cfg.params.get("primary", "off")
            logger.info("Preparing cam %s with params=%s", cam.name, params)
            new_cfg = dataclasses.replace(
                cfg,
                record_mode=record_mode,
                record_prebuffer_duration=0,
                is_enabled=True,
                is_record_enabled=True,
                params=params,
            )
            cam.load_configuration(new_cfg)
            cam.project = project

        #

        for cam in cameras:
            if cam.is_primary:
                logger.info("%s: prepare capture ..", cam.name)
                if not cam.on_prepare_capture():
                    raise RuntimeError(f"{cam.name}.on_prepare_capture() failed")
                cam.wait_for_capture_status(CaptureProcessStatus.RUNNING, timeout=5)

        for cam in cameras:
            if not cam.is_primary:
                logger.info("%s: prepare capture ..", cam.name)
                if not cam.on_prepare_capture():
                    raise RuntimeError(f"{cam.name}.on_prepare_capture() failed")

        wait_cams_capture_status(CaptureProcessStatus.RUNNING, timeout=5)

        for cam in cameras:
            if not cam.is_primary:
                logger.info("%s: capture start ..", cam.name)
                cam.on_capture_start()
        for cam in cameras:
            if cam.is_primary:
                logger.info("%s: capture start ..", cam.name)
                cam.on_capture_start()

        if record_mode == VideoRecordMode.TRIGGER:
            logger.info("Triggering recording")
            for cam in cameras:
                cam.on_trigger_recording(True)

        logger.notice("Waiting RECORDING on cams")
        wait_cams_capture_status(CaptureProcessStatus.RECORDING, 5)

    def run():
        logger.notice("Running 3d calib ..")

        max_requests = 1
        cur_requests = []
        #
        time.sleep(0.05)
        logger.info("Now executing calib moves ..")

        for coord, value in moves:
            if len(cur_requests) >= max_requests:
                front = cur_requests.pop(0)
                with hard.wait_pending_command_acked({front}):
                    pass
            logger.verbose("coord-%s -> %s", coord, value)
            key = coord2m[coord](value)
            cur_requests.append(key)

        with hard.wait_pending_command_acked(set(cur_requests)):
            logger.info("Waiting remaining move requests acked ...")

        logger.success("executed %s moves", len(moves))

        if record_mode == VideoRecordMode.TRIGGER:
            logger.info("Requesting cameras stop recording")
            for cam in reversed(cameras):
                cam.on_trigger_recording(False)
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
        for camera in reversed(cameras):
            logger.info("%s: notify end cam", camera.name)
            camera.on_capture_notify_end()
        for camera in reversed(cameras):
            logger.info("%s: stopping cam", camera.name)
            camera.on_capture_stop()
        hard.disconnect()
        wait_cams_capture_status(CaptureProcessStatus.TERMINATED, 5)
        logger.verbose("Resetting cams to previous config")
        for camera, cam_cfg in zip(cameras, cams_before_cfg):
            camera.load_configuration(cam_cfg)

    if failed is not None:
        raise failed

    for camera in cameras:
        vp = Path(project.get_video_path(
            camera.name,
            allow_overwrite=True,
            interval=ProjectInterval.HOUR if record_mode == VideoRecordMode.CONTINUOUS else ProjectInterval.NONE
        )[0])
        target = src_dir.joinpath(f"source_videos/{camera.name}.mp4")
        logger.verbose("%s -> %s", vp.as_posix(), target.as_posix())
        vp.rename(target)

    logger.notice("Processing capture in %s", src_dir)
    process_capture(src_dir.as_posix())

    # strip the session prefix from any path in the resulting processed directory:
    prefixed_str = f"{sess_path.prefix}_"
    renamed = 0
    for path in src_dir.rglob("*"):
        if path.name.startswith(prefixed_str):
            path.rename(path.parent.joinpath(path.name[len(prefixed_str):]))
            renamed += 1
    logger.debug("renamed %s files from session and 3d processing", renamed)

    logger.success("Successfully processed capture")

    return src_dir
