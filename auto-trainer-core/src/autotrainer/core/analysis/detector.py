import dataclasses
import datetime
import inspect
import math
import queue
import threading
import time
import typing
import warnings
from functools import partial
from typing import Dict, Tuple, Optional, Union, ClassVar, TypeVar, Type, Generic, List, Set, Callable, Any

import typing_extensions
from autotrainer.api import ApiEventKind, ApiDetectorKind
from autotrainer.core import ObservableObject, get_perf_now
from autotrainer.core.configuration.detector import DetectorConfig, GroupSubDetectorConfig
from autotrainer.core.event import post_api_detector_event_content
from autotrainer.core.event.event_manager import EventManager
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import no_op_timer, make_daemon_timer


logger = get_verbose_logger(__name__)


_request_check_state = object()


DetectorConfigT = TypeVar("DetectorConfigT", bound=DetectorConfig)


registered_detector_classes: List["BaseDetector"] = []


def has_kwarg(func, kwarg_name):
    # Get the function's signature
    sig = inspect.signature(func)

    # 1. Check if the specific keyword argument name exists
    if kwarg_name in sig.parameters:
        param = sig.parameters[kwarg_name]
        # Ensure it's not a positional-only argument
        return param.kind != inspect.Parameter.POSITIONAL_ONLY

    # 2. Check if the function accepts arbitrary keyword arguments (**kwargs)
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())


class BaseDetector(ObservableObject, Generic[DetectorConfigT]):

    IS_ENGAGED = "is_engaged"
    IS_ENGAGED_PROPERTY = IS_ENGAGED  # synonym

    CONFIG = "config"

    config_cls: Type[DetectorConfigT] = DetectorConfig

    use_daemon: bool = False
    default_timer_delay: Optional[float] = None

    detector_api_kind: ClassVar[Optional[ApiDetectorKind]] = None
    default_detector_enabled: ClassVar[bool] = True  # raw base detectors are always "enabled" by default

    def __init__(self, *, name: Optional[str] = None, config: Optional[DetectorConfigT] = None):
        super().__init__()
        if name is None:
            name = self.__class__.__qualname__
        self._name = name
        self._config = self.config_cls() if config is None else config
        self._running = False
        self._p_started = -math.inf
        self._started_datetime = datetime.datetime.now()
        self._is_engaged = False
        self._force_engaged = False  # only used for dev/testing
        self._engaged_perf_c = -math.inf
        self._disengaged_perf_c = -math.inf
        self._cur_timer = no_op_timer
        self._thread_queue: Optional[Tuple[threading.Thread, queue.Queue]] = None
        self._lock = threading.RLock()
        self._checking_state = False
        self._logger = get_verbose_logger(self.__class__.__module__)
        self._event_manager = EventManager.default()
        if not has_kwarg(self._check_state, "force"):
            def _check_state(*, force: bool = False, orig_check_state=self._check_state):
                del force  # unused
                return orig_check_state()
            self._check_state = _check_state

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        registered_detector_classes.append(cls)

    @property
    def name(self) -> str:
        return self._name

    @property
    def config(self) -> DetectorConfigT:
        return self._config

    @config.setter
    def config(self, config: DetectorConfigT):
        self._set_config(config)

    def _set_config(self, value: DetectorConfigT):
        self._logger.debug("got new config: %s", value)
        prev, self._config = self._config, value
        self.property_changed(self.CONFIG, value, prev)
        self.check_state()  # force check_state even if same config

    def post_detector_event(self, detector_id: ApiDetectorKind, active: bool, enabled: Optional[bool] = None):
        if enabled is None:
            enabled = self._running
        post_api_detector_event_content(self._event_manager, detector_id, active, enabled)

    @property
    def running(self):
        return self._running

    @property
    def started_at(self) -> datetime.datetime:
        return self._started_datetime

    @property
    def is_engaged(self):
        return self._is_engaged or self._force_engaged

    @is_engaged.setter
    def is_engaged(self, value):
        self.set_is_engaged(value)

    def _custom_set_is_engaged(self):
        """this is for subclass to customize their logic on is_engaged changed"""

    def set_is_engaged(self, engaged: bool):
        engaged |= self._force_engaged
        with self._lock:
            # safer,
            # ensure transition won't be lost if 2 threads modify/calls at same time
            prev, self._is_engaged = self._is_engaged, engaged
            if prev == engaged:
                return
            perf_now = get_perf_now()
            if engaged:
                self._engaged_perf_c = perf_now
            else:
                self._disengaged_perf_c = perf_now
        self._logger.notice("is_engaged -> %s (age previous = %.1f)",
                            engaged, perf_now - (self._disengaged_perf_c if engaged else self._engaged_perf_c))
        kind = self.detector_api_kind
        if kind is not None:
            self.post_detector_event(kind, engaged, self.default_detector_enabled)
        self._custom_set_is_engaged()  # before the property changed event
        self.property_changed(self.IS_ENGAGED, engaged, prev)

    @property
    def engaged_age(self):
        with self._lock:
            return (get_perf_now() if self._is_engaged else self._disengaged_perf_c) - self._engaged_perf_c

    @property
    def disengaged_age(self):
        with self._lock:
            return (get_perf_now() if not self._is_engaged else self._engaged_perf_c) - self._disengaged_perf_c

    def _make_new_timer(self, delay: float):
        self._cur_timer.cancel()  # safer
        timer = self._cur_timer = make_daemon_timer(delay, self.check_state)
        timer.start()
        self._logger.verbose("created timer to check_state within %.1fs", delay)

    @typing_extensions.override
    def _check_state(self) -> Optional[float]: ...

    @typing_extensions.override
    def _check_state(self, *, force: bool) -> Optional[float]: ...

    def _check_state(self, *, force: bool=False) -> Optional[float]:
        raise NotImplementedError

    def check_state_if_not_detector_thread(self):
        th_q = self._thread_queue
        if th_q is None or threading.current_thread() != th_q[0]:
            self.check_state()

    def check_state(self, *, force: bool=False):
        with self._lock:
            if not self._running and not force:
                return None
            th_q = self._thread_queue
            if th_q is not None:
                # if it's daemon detector, and it's running, put request_check_state to it:
                th, th_q = th_q
                if th is not threading.current_thread() and th.is_alive():
                    th_q.put(_request_check_state)
                    return None
            if self._checking_state:
                logger.warning("checking_state already in progress")
                return None
            self._checking_state = True
            try:
                next_delay = self._check_state(force=force)
            except Exception as err:
                self._logger.exception("_check_state() failed: %s", err)
                next_delay = 1
                # if not daemon detector, this will create a timer for another check in 1s
            finally:
                self._checking_state = False

            if next_delay is None:
                next_delay = self.default_timer_delay
            elif next_delay < 0:
                warnings.warn(f"received negative next_delay: {next_delay:.1f}")
                next_delay = 1
            if next_delay is not None and not self.use_daemon:
                # "recurrent/timed" detector
                self._make_new_timer(next_delay)
            else:
                # daemon detector or detector that will resume by explicit refresh,
                # or that is manually checked.
                self._cur_timer.cancel()
                self._cur_timer = no_op_timer
        return next_delay

    def _start(self):
        """Allow any subclass to customize its start procedure. super() should be called."""

    def start(self):
        with self._lock:
            if self._running:
                self._logger.debug("requested start but already running")
                return
            self._logger.verbose("%s: starting monitor", self._name)
            self._running = True
            self.is_engaged = False  # force reset "engaged" to False
            self._p_started = get_perf_now()
            self._started_datetime = datetime.datetime.now()
            self._start()
            if self.use_daemon:
                cmd_queue = queue.Queue(maxsize=32)
                thread = threading.Thread(name=self._name, target=self._daemon_run, daemon=True,
                                          args=(cmd_queue,))
                self._thread_queue = thread, cmd_queue  # set before start
                thread.start()
            else:
                self.check_state()

    def _daemon_run(self, cmd_queue):
        log = self._logger
        log.info("%s running", self._name)
        while self._running:
            delay = self.check_state()  # always check immediately
            if delay is None:
                delay = self.default_timer_delay
                if delay is None:
                    delay = 1
            # Now limit max delay to 60 seconds,
            # so that any change in config will be handled at most every 60 seconds.
            # Some detector, like global animal presence, could use very long delay between check,
            # so this ensures that if its setting relating to the delay is changed, then the new one will be handled,
            # ~relatively quickly.
            # Otherwise, we would need to restart any of them that has its config updated.
            delay = min(60., delay)
            try:
                r = cmd_queue.get(timeout=delay)
            except queue.Empty:
                continue
            cmd_queue.task_done()
            if r is _request_check_state:
                continue
            if r is None:
                break
            log.warning("unhandled command object: %r", r)
        # end while True
        log.verbose("%s: exiting main loop", self._name)

    def _stop(self):
        pass

    def stop(self):
        log = self._logger
        with self._lock:
            self._cur_timer.cancel()
            if not self._running:
                return
            log.verbose("%s: stopping monitor", self._name)
            self._running = False
            thread_queue = self._thread_queue
            self._thread_queue = None
            self._stop()
        # don't try join check thread with the lock acquired, given that can deadlock otherwise.
        if thread_queue is not None:
            thread, q = thread_queue
            # assert isinstance(q, queue.Queue)
            if thread != threading.current_thread():
                if thread.is_alive():
                    q.put(None)
                log.debug("Joining check thread %s", thread)
                thread.join(3)
                if thread.is_alive():
                    self._logger.warning("check thread still alive, but continuing anyway")
                else:
                    log.verbose("joined check thread %s", thread)

    def restart(self):
        self._logger.notice("Restarting %s", self._name)
        self.stop()
        self.start()

    def force_engaged(self, engaged: bool) -> None:
        """
        Primarily used for testing.  This will force the detector to be engaged if called with True.
        """
        self._force_engaged = engaged
        self.is_engaged = engaged


@dataclasses.dataclass
class GroupSubDetectorContext:
    detector: BaseDetector[GroupSubDetectorConfig]
    property_changed_callback: Callable



GroupSubDetectorT = TypeVar("GroupSubDetectorT", bound=BaseDetector[GroupSubDetectorConfig])


class GroupBaseDetector(BaseDetector[DetectorConfigT], Generic[DetectorConfigT, GroupSubDetectorT]):
    """Group Detector base class, is ORing of the sub-detectors"""

    DETECTOR_PROPERTY_CHANGED = "detector_property_changed"

    def __init__(self, *, name: Optional[str] = None, config: Optional[DetectorConfigT] = None):
        super().__init__(name=name, config=config)
        self._engaged_reasons: Set[str] = set()
        self._sub_detectors: Dict[str, GroupSubDetectorContext] = {}

    @property
    def engaged_reasons(self) -> List[str]:
        """Gives list of name/key of the engaged detectors"""
        with self._lock:
            return sorted(self._engaged_reasons)

    def _start(self):
        super()._start()
        self._engaged_reasons.clear()
        for sub in self._sub_detectors.values():
            sub.detector.start()

    def _stop(self):
        super()._stop()
        for sub in self._sub_detectors.values():
            sub.detector.stop()

    @property
    def sub_detectors(self) -> Dict[str, GroupSubDetectorT]:
        with self._lock:
            return {
                name: ctx.detector
                for name, ctx in self._sub_detectors.items()
            }

    def get_sub_detector(self, name: str) -> Optional[GroupSubDetectorT]:
        with self._lock:
            ctx = self._sub_detectors.get(name, None)
        return None if ctx is None else ctx.detector

    def register_sub_detector(self, name: str, detector: GroupSubDetectorT):
        ctx = GroupSubDetectorContext(
            detector=detector,
            property_changed_callback=partial(self._on_sub_detector_property_changed, detector),
        )
        with self._lock:
            self.unregister_sub_detector(name)
            detector.property_changed += ctx.property_changed_callback
            self._sub_detectors[name] = ctx

    def unregister_sub_detector(self, name: str) -> Optional[GroupSubDetectorT]:
        with self._lock:
            ctx = self._sub_detectors.pop(name, None)
            if ctx is None:
                return None
            ctx.detector.property_changed -= ctx.property_changed_callback
        return ctx.detector

    def _on_sub_detector_property_changed(self, detector: GroupSubDetectorT, name: str, value, old_value):
        if name in (detector.IS_ENGAGED, detector.CONFIG):
            self.check_state()
        self.property_changed(self.DETECTOR_PROPERTY_CHANGED, (detector, name, value), old_value)

    def _check_state(self, *, force: bool=False) -> Optional[float]:
        prev_engaged = self._engaged_reasons.copy()
        new_engaged = set()
        for sub_name, sub_ctx in self._sub_detectors.items():
            det = sub_ctx.detector
            if not det.use_daemon and not det.default_timer_delay:
                det.check_state(force=force)
            cfg = det.config
            det_engaged = det.is_engaged
            is_group_sub_det_cfg = isinstance(cfg, GroupSubDetectorConfig)  # allow be flexible.
            if det_engaged:
                if is_group_sub_det_cfg:
                    keep = cfg.use
                else:
                    keep = True
                if keep:
                    new_engaged.add(sub_name)
            elif is_group_sub_det_cfg:
                assert not det_engaged  # per the previous if.
                if sub_name in prev_engaged:
                    if not cfg.allow_autoresume_on_cleared:
                        new_engaged.add(sub_name)  # keep it
        if new_engaged != prev_engaged:
            # ensure IS_ENGAGED property changed event still always relayed,
            # even if same is_engaged, so that listeners will get/see the new_engaged reasons/sub-detectors.
            self._is_engaged = None
        self._engaged_reasons = new_engaged
        self.is_engaged = len(new_engaged) > 0
