import abc
import os
import math
import statistics
from typing import Callable, Optional, List, Union, Protocol, Any

from autotrainer.behavior import BehaviorAlgorithm, PelletDeviceProtocol
from autotrainer.core import Offset3DTuple, calculate_std_dev_manual, ObservableObject, get_verbose_logger, ProjectInfo, \
    mean_method
from autotrainer.core.configuration.behavior_configuration import (
    ShiftXYZBufferHandlerConfig,
    ShiftXYZHandlerConfig,
)

from autotrainer.inference.analysis import IntersessionResponse


logger = get_verbose_logger(__name__)


class ProcessedShiftXYZCallbackHandler(Protocol):

    def __call__(self, project: ProjectInfo, shift: Offset3DTuple) -> None:
        """Signature of ProcessedShiftXYZCallbackHandler"""


ProcessedShiftXYZCallbackHandlerT = Optional[ProcessedShiftXYZCallbackHandler]


class ShiftXYZBaseHandler(abc.ABC):

    @abc.abstractmethod
    def reset(self):
        """Ensure cleared state"""

    @abc.abstractmethod
    def __call__(
        self, rsp: IntersessionResponse, *, reduce_method=mean_method,
    ) -> Optional[Offset3DTuple]:
        """Process/accumulate one intersession response,
        return None if the response does not generate yet a full shift XYZ result"""

    @abc.abstractmethod
    def make_shift_from_rh_list(self, rh_list: List[Offset3DTuple],
                                *, reduce_method=mean_method) -> Offset3DTuple:
        """Compute the full shift from an entire RH max vp list"""

    @abc.abstractmethod
    def get_context(self) -> Any:
        """Return the associated context with this handler"""


class ShiftXYZBufferHandler(ShiftXYZBaseHandler):

    def __init__(
        self,
        *,
        config: ShiftXYZBufferHandlerConfig,
    ):
        self._config = config
        self._failed_reaches_buffer: List[Offset3DTuple] = []

    def reset(self):
        self._failed_reaches_buffer.clear()

    def __call__(self, rsp: IntersessionResponse, *, reduce_method=mean_method):
        current_buffer = self._failed_reaches_buffer
        current_buffer.extend(rsp.rh_max_vp_list)
        cfg = self._config
        if len(current_buffer) < cfg.minimum_reach_fail:
            return None
        shift = self.make_shift_from_rh_list(current_buffer, reduce_method=reduce_method)
        current_buffer.clear()
        return shift

    def make_shift_from_rh_list(
        self,
        rh_list: List[Offset3DTuple],
        *,
        reduce_method=mean_method,
    ) -> Offset3DTuple:
        if len(rh_list) == 0:
            return Offset3DTuple.get_nan()
        cfg = self._config
        if len(rh_list) == 1:
            mean_off = rh_list[0]
            stdev_off = Offset3DTuple.get_zero()
        else:
            mean_off, stdev_off = calculate_std_dev_manual(rh_list, reduce_method=reduce_method)
        #
        off_x, off_y, off_z = mean_off - cfg.target
        # assert isinstance(res_off, Offset3DTuple)
        #
        shift_x = off_x if abs(off_x) > 0.5 else 0
        shift_y = off_y if abs(off_y) > 1 else 0
        shift_z = off_z if abs(off_z) > 0.5 else 0
        #
        final_shift = Offset3DTuple(shift_x, shift_y, shift_z)
        logger.verbose(
            "shift compute result: %s ; rh-buffer=%s rh-stdev=%s",
            final_shift.round(1), [o.round(1) for o in rh_list], stdev_off.round(1))
        #
        return final_shift

    def get_context(self) -> Any:
        return dict(failed_reaches_buffer=self._failed_reaches_buffer)


class ShiftXYZHandler(ObservableObject):

    LAST_SHIFT_XYZ = "last_shift_xyz"
    LAST_PROCESSED_SHIFT_XYZ = "last_processed_shift_xyz"

    def __init__(self, *, algo: BehaviorAlgorithm):
        super().__init__()
        self._algo = algo
        self._config = algo.active_config.shift_xyz_handler
        self._processed_shift_handler: ProcessedShiftXYZCallbackHandlerT = None
        self._last_shift_xyz = Offset3DTuple.get_nan()
        self._last_processed_shift_xyz = Offset3DTuple.get_nan()
        self._batch_has_tongue_eaten = False
        self._new_shift_y_limit: Optional[float] = None
        self._result_handler = ShiftXYZBufferHandler(config=ShiftXYZBufferHandlerConfig())
        # set config again, to ensure result_handler will be correct one
        self.set_config(algo.active_config.shift_xyz_handler)

    def set_config(self, config: ShiftXYZHandlerConfig) -> ShiftXYZBaseHandler:
        sel = config.selected
        if sel == "ShiftXYZBufferHandler":
            handler = ShiftXYZBufferHandler(config=config.buffer)
        else:
            raise ValueError(f"Unknown/unhandled shift-xyz handler {sel}")
        self._config = config
        self.set_handler(handler)
        self.reset()
        return handler

    def reset(self):
        self._result_handler.reset()
        self._batch_has_tongue_eaten = False
        self._new_shift_y_limit = None
        self.last_processed_shift_xyz = self.last_shift_xyz = Offset3DTuple.get_nan()

    @property
    def last_shift_xyz(self) -> Offset3DTuple:
        return self._last_shift_xyz

    @last_shift_xyz.setter
    def last_shift_xyz(self, value):
        prev, self._last_shift_xyz = self._last_shift_xyz, value
        # use property_changed, which always call the property changed callbacks, even if same value than prev:
        self.property_changed(self.LAST_SHIFT_XYZ, value, prev)

    #

    @property
    def last_processed_shift_xyz(self) -> Offset3DTuple:
        return self._last_processed_shift_xyz

    @last_processed_shift_xyz.setter
    def last_processed_shift_xyz(self, value: Offset3DTuple):
        logger.info("Got new processed shift XYZ: %s", value.round(1))
        prev, self._last_processed_shift_xyz = self.last_processed_shift_xyz, value
        # use property_changed, which always call the property changed callbacks, even if same value than prev:
        self.property_changed(self.LAST_PROCESSED_SHIFT_XYZ, value, prev)

    #

    @property
    def handler(self) -> ShiftXYZBaseHandler:
        return self._result_handler

    def set_handler(self, handler: ShiftXYZBaseHandler):
        self._result_handler = handler

    def set_processed_handler(self, func: ProcessedShiftXYZCallbackHandlerT):
        self._processed_shift_handler = func

    def put_intersession_response(
        self,
        project: ProjectInfo,
        trial_result: IntersessionResponse,
        *,
        is_batch: bool = False,
        is_first: bool = True,
        is_last: bool = True,
        reduce_method=mean_method,
    ):
        algo = self._algo
        cfg = algo.active_config.shift_xyz_handler
        if self._new_shift_y_limit is None:
            prev_y_limit = algo.pellet_shift_y_limit
        else:
            prev_y_limit = self._new_shift_y_limit

        if is_batch:
            if is_first:
                logger.info("Received first (batch) trial")
                self._batch_has_tongue_eaten = False
            if is_last:
                logger.info("Received last batch trial")

        send_pos = project.dcs_send_position
        if send_pos is None:
            logger.warning("skipping trial result given no dcs_send_pos ; project=%s", project)
            return
        tongue_eaten = False
        for evt in trial_result.other_events:
            if evt.outcome == "eaten" and evt.method == "tongue":
                tongue_eaten = True
                if is_batch:
                    self._batch_has_tongue_eaten = True
                break
        if not tongue_eaten and not self._batch_has_tongue_eaten:
            # "normal" case
            trial_shift = self._result_handler.make_shift_from_rh_list(trial_result.rh_max_vp_list,
                                                                       reduce_method=reduce_method)
            processed_shift = self._result_handler(trial_result, reduce_method=reduce_method)
            if processed_shift is not None and prev_y_limit is not None:
                if processed_shift.y + send_pos.y < prev_y_limit:
                    processed_shift = processed_shift.replace(
                        y=prev_y_limit - send_pos.y
                    )
                    logger.info("Processed shift-Y limited to %s", processed_shift.y)
        elif tongue_eaten:
            self._result_handler.reset()  # always
            trial_shift = cfg.tongue_eaten_shift
            processed_shift = trial_shift
            logger.verbose("checking new tongue-eaten against previous: send_pos_y=%s prev_y_limit=%s",
                           send_pos.y, prev_y_limit)
            new_y_limit = None
            if prev_y_limit is None:
                new_y_limit = send_pos.y + trial_shift.y
            else:
                if send_pos.y > prev_y_limit:
                    new_y_limit = send_pos.y
            if new_y_limit is not None:
                self._new_shift_y_limit = new_y_limit
        else:
            trial_shift = processed_shift = None
        #
        if is_last:
            if self._batch_has_tongue_eaten:
                self._result_handler.reset()  # always at end of batch
                self._batch_has_tongue_eaten = False
            new_y_limit = self._new_shift_y_limit
            if new_y_limit is not None:
                logger.notice("Setting new pellet_shift_y_limit: %s", new_y_limit)
                algo.pellet_shift_y_limit = new_y_limit
                self._new_shift_y_limit = None
        #
        if trial_shift is not None:
            self.last_shift_xyz = trial_shift
        if processed_shift is not None:
            self.last_processed_shift_xyz = processed_shift
            func = self._processed_shift_handler
            if func is None:
                logger.debug("handle_processed_shift_func undefined")
            else:
                func: ProcessedShiftXYZCallbackHandler
                func(project, processed_shift)
