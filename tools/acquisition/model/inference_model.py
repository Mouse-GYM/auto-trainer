import ctypes
import multiprocessing.pool
import os
import queue
import math
import signal
import threading
import time
from multiprocessing import synchronize
from multiprocessing.managers import ValueProxy
from multiprocessing.sharedctypes import Synchronized
from multiprocessing.synchronize import Semaphore as SemaphoreType
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any
from threading import Thread

from autotrainer.api import build_event, ApiEventKind

from autotrainer.core import FixedArrayMultiQueue, ProjectInfo, EventManager, clear_queue, \
    InferenceConfiguration, Offset3DTuple, get_perf_now
from autotrainer.core.project import ProjectDependentProtocol
from autotrainer.core.multiproc import get_mp_ctx, pool_init
from autotrainer.core.logging import get_verbose_logger, make_log_dict_config
from autotrainer.core.pose_elements import SceneElement, AllHandsParts

from autotrainer.inference import PoseProcess, InferenceCommandMessageKind, InferenceStatusMessageKind, PoseAlgorithm, \
    InferenceMode, InferenceStatus, InferenceMonitorDataMsg
from autotrainer.inference.pose_result_process import InferenceMonitorDataProc
from autotrainer.inference.analysis import intertrial_process, IntertrialResponse

from autotrainer.behavior import SegmentationConfiguration, DetectionConfiguration, \
    InferenceProtocol, IntertrialBlock, IntertrialDetection, BehaviorAlgorithm


logger = get_verbose_logger(__name__)

# even better is to use __debug__ and use "python -O ..."
# see https://docs.python.org/3/using/cmdline.html#cmdoption-O
_local_do_debug = False


class InferenceModel(InferenceProtocol, ProjectDependentProtocol):

    IS_ENABLED = "is_enabled"
    IS_PREDICT_ENABLED = "is_predict_enabled"
    MODEL_LOCATION = "model_location"

    def __init__(self,
        pose_algorithm: PoseAlgorithm,
        *,
        calib_dir: Optional[Path] = None,
        record_stop_sema: Optional[SemaphoreType] = None,
        mp_manager=None,
        main_watchdog_holder: Optional[ValueProxy] = None,
    ):
        super().__init__()

        mp_ctx = get_mp_ctx() if mp_manager is None else mp_manager
        self._event_manager = EventManager.default()
        self._mp_manager = mp_ctx
        self._thread_lock = threading.RLock()  # for perform_detection / perform_segmentation
        self._output_data_queue = mp_ctx.Queue(maxsize=64)  # inference result data queue
        self._cmd_queue_lock = threading.Lock()  # to ensure ack are correct respectively
        self._cmd_queue = mp_ctx.Queue(maxsize=16)  # command queue to inference process
        self._cmd_queue_ack = mp_ctx.Event()
        self._notif_msg_queue = mp_ctx.Queue(maxsize=64)  # msg queue for messages from pose-process and from data-monitor process to main process
        self._data_monitor_cmd_queue = mp_ctx.Queue(maxsize=16)  # command queue to monitor data result process
        self._data_monitor_cmd_ack_event = mp_ctx.Event()
        self._record_stop_sema = record_stop_sema
        self._main_watchdog_holder: Optional[ValueProxy] = main_watchdog_holder

        self._offline_queue: Optional[FixedArrayMultiQueue] = None
        self._offline_segmentation_thread: Optional[Thread] = None
        self._offline_analysis_thread: Optional[Thread] = None

        self._is_enabled = False
        self._model_location = ""
        self._pose_algorithm = pose_algorithm
        self._pose_parts: List[str] = []
        self._calib_dir = calib_dir

        self._msg_thread: Optional[threading.Thread] = None

        self._data_monitor_watchdog_perf_c = mp_ctx.Value(ctypes.c_double, math.nan)
        self._data_monitor_proc: Optional[InferenceMonitorDataProc] = None

        self._pose_process_watchdog_perf_c = mp_ctx.Value(ctypes.c_double, math.nan)
        self._pose_process: Optional[PoseProcess] = None
        self._is_predict_enabled = True
        self._status = InferenceStatus.stopped

        self._frames_per_camera = 0
        self._frame_width = 1
        self._frame_height = 1

        self._project: ProjectInfo = ProjectInfo.get_null_project()
        self._intertrial_block: Optional[IntertrialBlock] = None
        self._intertrial_detection: Optional[IntertrialDetection] = None
        self._parts_offsets: Dict[Tuple[SceneElement, SceneElement], Offset3DTuple] = {}
        self._pair_offsets_2_handler = {
            (SceneElement.Diamond, SceneElement.Triangle): self.diamond_triangle_offset_changed,
            (SceneElement.Star, SceneElement.Triangle): self.star_triangle_offset_changed,
            (SceneElement.Triangle, SceneElement.Pellet): self.triangle_pellet_offset_changed,
            **{
                (SceneElement.Pellet, hand_part): lambda _: None  # this will be sub-handled in behavior algo
                for hand_part in AllHandsParts
            },
        }
        self._process_pool: Optional[multiprocessing.pool.Pool] = None

    @property
    def watchdog_pose_process_perf_c(self) -> float:
        pose_proc = self._pose_process
        if pose_proc is not None:
            return self._pose_process_watchdog_perf_c.value
        return math.nan

    @property
    def watchdog_monitor_data_proc_perf_c(self) -> float:
        proc = self._data_monitor_proc
        if proc is not None:
            return self._data_monitor_watchdog_perf_c.value
        return math.nan

    @property
    def project(self) -> ProjectInfo:
        return self._project

    @project.setter
    def project(self, value: ProjectInfo):
        self._project = value
        logger.debug("Putting new project info to data monitor queue: %s", value)
        self._data_monitor_cmd_ack_event.clear()
        self._data_monitor_cmd_queue.put((InferenceMonitorDataMsg.SET_PROJECT_INFO, (value,), None))
        cur_proc = self._data_monitor_proc
        if cur_proc is None:
            # can happen on startup before inference running/started
            logger.verbose("data_monitor_proc not yet started, won't wait ack event")
            # when it will start it will get the put project-info
        else:
            # inference data monitor proc could have been killed/died unexpectedly,
            # it can be started again with start.
            if cur_proc.is_alive():
                logger.debug("waiting ack, proc=%s", cur_proc)
                self._data_monitor_cmd_ack_event.wait()
                logger.debug("ack obtained")

    @property
    def pose_parts(self) -> List[str]:
        return self._pose_parts

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value: bool):
        prev, self._is_enabled = self._is_enabled, value
        self._on_property_changed(self.IS_ENABLED, value, prev)

    @property
    def is_predict_enabled(self) -> bool:
        return self._is_predict_enabled

    @is_predict_enabled.setter
    def is_predict_enabled(self, value: bool):
        prev, self._is_predict_enabled = self._is_predict_enabled, value
        self._on_property_changed(self.IS_PREDICT_ENABLED, value, prev)

    @property
    def model_location(self) -> str:
        return self._model_location

    @model_location.setter
    def model_location(self, value: str):
        prev, self._model_location = self._model_location, value
        self._on_property_changed(self.MODEL_LOCATION, value, prev)

    @property
    def status(self) -> InferenceStatus:
        return self._status

    def _set_status(self, value: InferenceStatus):
        prev, self._status = self._status, value
        self._on_property_changed(self.STATUS, value, prev)

    def wait_for_status(self, status: InferenceStatus, *, timeout: float):
        p_timeout = get_perf_now() + timeout
        while self._status != status:
            if get_perf_now() > p_timeout:
                raise RuntimeError(f"Timeout waiting inference status {status}")
            time.sleep(0.001)

    @property
    def pose_algorithm(self) -> PoseAlgorithm:
        return self._pose_algorithm

    @pose_algorithm.setter
    def pose_algorithm(self, value):
        self._pose_algorithm = value
        proc = self._data_monitor_proc
        if proc is not None and proc.is_alive():
            logger.debug("putting new pose_algo to data-monitor-proc")
            self._data_monitor_cmd_queue.put(
                (InferenceMonitorDataProc.Msg.SET_POSE_ALGO, (value,), None))

    @staticmethod
    def _check_previous_offline_thread(cause: str, cur_off: Optional[threading.Thread]):
        # protection, if we need more than 1 executing thread at the same time then we need a list to retain the
        # threads instead of only one of them.
        if cur_off is None:
            return
        perf_now = time.perf_counter()
        was_alive = cur_off.is_alive()
        if was_alive:
            logger.warning("%s request but previous offline thread still alive: %s, join might block ~long",
                           cause, cur_off)
        cur_off.join()
        if was_alive:
            logger.verbose("Waited %.1fs to join previous offline thread", time.perf_counter() - perf_now)

    def perform_segmentation(self, configuration: SegmentationConfiguration) -> Optional[SegmentationConfiguration]:
        with self._thread_lock:
            return self._perform_segmentation(configuration)

    def _perform_segmentation(self, configuration: SegmentationConfiguration) -> Optional[SegmentationConfiguration]:
        if self._intertrial_block is not None:
            logger.error("_intertrial_block not None, segmentation already started. block=%s segment_cfg=%s",
                         self._intertrial_block, configuration)
            return None
        logger.notice("performing segmentation on %s", configuration)
        self._intertrial_block = IntertrialBlock(configuration=configuration)
        return configuration

    def perform_detection(self, configuration: DetectionConfiguration) -> Optional[DetectionConfiguration]:
        with self._thread_lock:
            return self._perform_detection(configuration)

    def _perform_detection(self, configuration: DetectionConfiguration):
        if self._intertrial_detection is not None:
            logger.warning("_intertrial_detection not None, skipping perform_detection")
            return None
        self._check_previous_offline_thread("perform_detection", self._offline_analysis_thread)
        intertrial_detection = self._intertrial_detection = IntertrialDetection(configuration)
        thread = self._offline_analysis_thread = Thread(
            target=self._intertrial_process, name="intertrial_process",
            args=(intertrial_detection,))
        thread.start()
        logger.info("performing detection analysis on %s", configuration)
        return configuration

    @staticmethod
    def _pool_init(log_dct_cfg):
        pool_init(log_dct_cfg)
        # pre-import the intertrial_process module, so that it's already imported on first analysis:
        from autotrainer.inference.analysis import intertrial_process
        logger.info("imported inference analysis intertrial_process: %s", intertrial_process)

    def start(self, live_queue: FixedArrayMultiQueue) -> bool:

        if self._process_pool is None:
            self._process_pool = multiprocessing.Pool(
                processes=1,  # we only need 1 atm
                initializer=self._pool_init,
                initargs=(make_log_dict_config(),),
                maxtasksperchild=int(os.getenv("INFERENCE_PROCESS_POOL_MAX_TASKS_PER_CHILD", 64)),
            )

        if self._msg_thread is None:
            thread = Thread(target=self._monitor_msg_queue, name="monitor_msg_queue", daemon=True)
            thread.start()
            self._msg_thread = thread

        data_monitor_proc = self._data_monitor_proc
        if data_monitor_proc is not None and not data_monitor_proc.is_alive():
            data_monitor_proc.join(3)
            data_monitor_proc = None

        if data_monitor_proc is None:
            self._data_monitor_watchdog_perf_c.value = get_perf_now()
            data_monitor_proc = self._data_monitor_proc = InferenceMonitorDataProc(
                project=self._project,
                pose_data_queue=self._output_data_queue,
                msg_queue=self._notif_msg_queue,
                cmd_queue=self._data_monitor_cmd_queue,
                cmd_ack_event=self._data_monitor_cmd_ack_event,
                frames_per_cam=live_queue.frames_per_camera,
                monitored_parts_offsets=list(self._pair_offsets_2_handler),
                watchdog_perf_c=self._data_monitor_watchdog_perf_c,
                main_watchdog_holder=self._main_watchdog_holder,
            )
            data_monitor_proc.start()

        self._frame_height, self._frame_width = live_queue.shape
        self._frames_per_camera = live_queue.frames_per_camera

        self._pose_process_watchdog_perf_c.value = get_perf_now()
        proc = self._pose_process = PoseProcess(
            live_queue,
            data_queue=self._output_data_queue,
            cmd_queue=self._cmd_queue,
            cmd_queue_ack=self._cmd_queue_ack,
            msg_queue=self._notif_msg_queue,
            model_location=self._model_location,
            stop_recorded_event=data_monitor_proc.stop_recorded,
            offline_input_event_cb_ack=self._mp_manager.Event(),
            watchdog_perf_c=self._pose_process_watchdog_perf_c,
            record_stop_sema=self._record_stop_sema,
            main_watchdog_holder=self._main_watchdog_holder,
        )
        proc.start()

        return True

    def stop(self):
        if self._status in {InferenceStatus.stopped, InferenceStatus.stopping}:
            logger.debug("requested stop but already stopped or in progress: %s", self._status)
            return
        self._set_status(InferenceStatus.stopping)
        logger.debug("stopping inference..")
        proc = self._pose_process
        if proc is not None:
            if proc.is_alive():
                self.send_message(InferenceCommandMessageKind.Terminate)
            logger.debug("<inference> waiting for process termination: %s", proc)
            t_timeout_sigint = time.perf_counter() + 30
            t_timeout_sigterm = time.perf_counter() + 60
            while True:
                perf_c = time.perf_counter()
                if perf_c > t_timeout_sigterm:
                    logger.warning("sending SIGTERM to %s", proc)
                    proc.terminate()
                    # os.kill(proc.pid, signal.SIGTERM)
                    break
                if perf_c > t_timeout_sigint:
                    t_timeout_sigint += 10
                    logger.warning("sending SIGINT to %s", proc)
                    proc.kill()
                    # os.kill(proc.pid, signal.SIGINT)
                if not proc.is_alive():
                    break
                time.sleep(0.1)
            proc.join()
            logger.info("<inference> process exited with %s", proc.exitcode)
            self._pose_process = None

            clear_queue(self._output_data_queue, name="inference_output_data_queue")
            clear_queue(self._notif_msg_queue, name="inference_notif_messages_queue")
            clear_queue(self._cmd_queue, name="inference_cmd_queue")

        self._stop_data_monitor_proc()
        clear_queue(
            self._data_monitor_cmd_queue, name="data_monitor_cmd_queue"
        )

        pool = self._process_pool
        if pool is not None:
            logger.verbose("Terminating process pool %s", pool)
            pool.close()
            pool.terminate()
            pool.join()
            logger.verbose("process pool joined and terminated %s", pool)
            self._process_pool = None

        for thread in (self._offline_segmentation_thread, self._offline_analysis_thread):
            if thread is not None:
                logger.debug("joining thread %s", thread)
                thread.join(3)
                if thread.is_alive():
                    logger.warning("thread %s still alive", thread)

        # always:
        self._intertrial_block = None
        self._offline_segmentation_thread = None
        self._offline_analysis_thread = None
        self._intertrial_detection = None
        # finally:
        self._set_status(InferenceStatus.stopped)

    def _stop_data_monitor_proc(self, timeout = 3):
        data_proc = self._data_monitor_proc
        if data_proc is None:
            return
        self._data_monitor_proc = None
        logger.debug("joining data_monitor_proc")
        data_monitor_cmd_queue = self._data_monitor_cmd_queue
        if data_proc.is_alive():
            data_monitor_cmd_queue.put(None)
        data_proc.join(timeout)
        if data_proc.exitcode is None:
            logger.warning("sending interrupt to monitor data process")
            os.kill(data_proc.pid, signal.SIGINT)
            data_proc.join(2)
            if data_proc.exitcode is None:
                logger.warning("terminating to monitor data process")
                data_proc.terminate()
                data_proc.join(1)
                if data_proc.exitcode is None:
                    logger.warning("killing monitor data process")
                    data_proc.kill()
                    data_proc.join(1)
            data_proc.on_close()
        logger.verbose("joined %s ; exit_code=%s", data_proc, data_proc.exitcode)

    def terminate(self, *, timeout: float = 5):
        logger.debug("terminating..")
        self.stop()

        msg_thread = self._msg_thread
        msg_queue = self._notif_msg_queue
        if msg_thread is not None:
            msg_queue.put(None)
            logger.debug("joining msg_thread")
            msg_thread.join()
            self._msg_thread = None

        logger.verbose("closing mp queues")
        for mp_q, name in (
            (self._data_monitor_cmd_queue, "data_monitor_cmd_queue"),
            (self._output_data_queue, "inference_output_data_queue"),
            (self._cmd_queue, "inference_cmd_queue"),
            (self._notif_msg_queue, "notif_msg_queue")
        ):
            if mp_q is not None:
                clear_queue(mp_q, log_dumped=True, name=name)
                if hasattr(mp_q, "close"):
                    logger.debug("queue: closing %s: size=%s", name, mp_q.qsize())
                    mp_q.close()
                    if hasattr(mp_q, "join_thread"):
                        mp_q.join_thread()
        self._data_monitor_cmd_queue = \
        self._output_data_queue = \
        self._cmd_queue = \
        self._notif_msg_queue = None

    def load_configuration(self, config: InferenceConfiguration):
        self.model_location = config.pose_model_location
        self.is_enabled = config.is_enabled

    def save_configuration(self) -> InferenceConfiguration:
        return InferenceConfiguration(
            pose_model_location=self.model_location,
            is_enabled=self.is_enabled,
        )

    def send_message(self, kind: InferenceCommandMessageKind, data: Optional[Any] = None):
        cmd_queue = self._cmd_queue
        # logger.debug("sending command msg %s qsize=%s", kind, cmd_queue.qsize())
        with self._cmd_queue_lock:
            self._cmd_queue_ack.clear()
            cmd_queue.put((kind, data))
            logger.debug("sent command msg %s qsize=%s", kind, cmd_queue.qsize())
            pose_proc = self._pose_process
            if pose_proc is not None and pose_proc.is_alive():
                if self._cmd_queue_ack.wait(3):
                    logger.debug("got cmd ack for %s", kind)
                else:
                    logger.warning("missed ack for %s within expected delay, continuing", kind)
            else:
                logger.verbose("pose-process not alive, skipped ack wait for %s", kind)

    def _handle_segmentation_finished(self, prj: ProjectInfo, success: bool, *, error: str="NA"):
        ib = self._intertrial_block
        if ib is None:
            logger.critical("Got segmentation_finished but intertrial_block is None ; prj=%s", prj)
        else:
            ib.configuration.complete(success, error=error)
            self._intertrial_block = None
            logger.notice("_intertrial_block -> None, after ib=%s and prj=%s", ib, prj)
        self.segmentation_finished(prj, success, error=error)

    def _cb_on_intertrial_segmentation_finished(self, project: ProjectInfo, success: bool, *, error: str= "NA"):
        logger.debug("_cb_on_intertrial_segmentation_finished: success=%s error=%s prj=%s", success, error, project)
        if success:
            self._event_manager.post_api_event(build_event(
                ApiEventKind.intertrialSegmentationSave,
                {"session_id": project.session_id, "trial_id": project.trial,
                 "location": project.get_trial_path().location}))
        else:
            self._event_manager.post_api_event(build_event(
                ApiEventKind.intertrialSegmentationSaveError,
                {"session_id": project.session_id, "trial_id": project.trial, "error": error}))
        self._handle_segmentation_finished(project, success, error=error)

    def _cb_on_set_feed_intertrial_result(self, project: ProjectInfo, error: Optional[str],
                                          *, event: Optional[synchronize.Event]=None):
        logger.verbose("Got feed error cb: prj=%s err=%s", project, error)
        self._data_monitor_cmd_ack_event.clear()
        self._data_monitor_cmd_queue.put((InferenceMonitorDataMsg.SET_FEED_INTERTRIAL_RESULT, (project, error), None))
        if not self._data_monitor_cmd_ack_event.wait(5):
            logger.warning("timeout wait ack for SET_FEED_INTERTRIAL_RESULT to pose result process")
        if event is not None:
            event.set()

    def _handle_monitor_data_proc_msg(self, msg, ctx):
        args, kwargs = ctx
        if msg is InferenceMonitorDataMsg.POSE_RESULT_READY:
            response = args[0]
            for pair_key, pair_handler in self._pair_offsets_2_handler.items():
                part1, part2 = pair_key
                prev = self._parts_offsets.get(pair_key, None)
                cur = response.get_parts_3d_offset(part1, part2)
                self._parts_offsets[pair_key] = cur
                try:
                    if prev != cur:
                        # if we wanted as "global" property event handling:
                        # self._on_property_changed(f"parts_offset_{part1}_{part2}", cur, prev)
                        pair_handler(cur)
                except Exception as err:
                    logger.exception("offset_changed event callback failed: %s", err)
            try:
                self.pose_response_ready(response)
            except Exception as err:
                logger.exception("pose_response_ready event callback failed: %s", err)

        elif msg is InferenceMonitorDataMsg.INTERTRIAL_SEGMENTATION_FINISHED:
            self._cb_on_intertrial_segmentation_finished(*args, **kwargs)

        elif msg is InferenceMonitorDataMsg.SET_FEED_INTERTRIAL_RESULT:
            self._cb_on_set_feed_intertrial_result(*args, **kwargs)

        else:
            logger.warning("unknown monitor proc data: %s - ctx=%s", msg, ctx)

    def _monitor_msg_queue(self):
        while True:
            try:
                raw = self._notif_msg_queue.get(timeout=0.1)
            except (EOFError, IOError, ValueError):
                break
            except queue.Empty:
                continue
            if raw is None:
                logger.notice("received None exit sentinel, exiting loop")
                break
            msg, context = raw
            try:
                if isinstance(msg, InferenceMonitorDataMsg):
                    self._handle_monitor_data_proc_msg(msg, context)
                    continue
                logger.debug("Processing msg %s ...", msg)
                if msg == InferenceStatusMessageKind.Initialized:
                    self._pose_parts = context
                    self._set_status(InferenceStatus.waiting)
                    pose_algo = self._pose_algorithm
                    pose_algo.initialize(context)
                    self._data_monitor_cmd_queue.put(
                        (InferenceMonitorDataProc.Msg.SET_POSE_ALGO, (pose_algo,), None))
                    self.send_message(InferenceCommandMessageKind.Start)
                elif msg == InferenceStatusMessageKind.Loading:
                    self._set_status(InferenceStatus.loading)
                elif msg == InferenceStatusMessageKind.Performance:
                    logger.info(f"{context :.1f} predict calls/s")
                    fps = context * self._frames_per_camera
                    logger.info(f"{fps :.1f} frames/camera/s ({(fps * 2):.1f} total frames/s)")
                elif msg == InferenceStatusMessageKind.Running:
                    mode = InferenceMode(context)
                    logger.info(f"predict running with {mode.name} queue")
                    self._set_status(InferenceStatus.live if mode == InferenceMode.Live
                                     else InferenceStatus.intertrial)
                elif msg in {
                    InferenceStatusMessageKind.Created,
                    InferenceStatusMessageKind.Terminated,
                }:
                    # no-op handler
                    pass
                else:
                    logger.warning("Unhandled msg: %s", msg)
            except Exception as err:
                logger.exception("Error processing msg %s: %s", msg, err)

    def _feed_intertrial_analysis_execute(self, intersession_block: IntertrialBlock):
        pass  # todo: adapt for simulate with main window app

    @staticmethod
    def _intertrial_process_execute(*args, **kwargs):
        return intertrial_process(*args, **kwargs)

    def _intertrial_process(self, intertrial_detection: IntertrialDetection):
        det_cfg = intertrial_detection.configuration
        project = det_cfg.project
        pool = self._process_pool
        try:
            assert pool is not None
            async_res = pool.apply_async(
                self._intertrial_process_execute,
                args=(project,),
                kwds=dict(
                    calib_dir=self._calib_dir,
                    frame_rate=det_cfg.frame_rate,
                ),
            )
            result = async_res.get()
        except Exception as err:
            logger.exception("Error processing intertrial: %s", err)
            processed_ok = False
            result = None
            error = str(err)
        else:
            processed_ok = True
            error = None

        if processed_ok:
            result: IntertrialResponse
            self._event_manager.post_api_event(build_event(
                ApiEventKind.intertrialDetectionSave,
                {"session_id": project.session_id, "trial_id": project.trial,
                 "location": project.get_trial_path().location}))
            # assert isinstance(result, IntersessionResponse)
            self.detection_result_ready(project, result)
        else:
            self._event_manager.post_api_event(build_event(
                ApiEventKind.intertrialDetectionSaveError,
                {"session_id": project.session_id, "trial_id": project.trial, "error": error or ""}))

        intertrial_detection.configuration.complete(processed_ok, error=error)
        self._intertrial_detection = None
