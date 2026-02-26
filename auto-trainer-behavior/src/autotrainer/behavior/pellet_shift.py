import abc
import os
import math
import statistics
from typing import Callable, Optional, List, Union

from autotrainer.core import Offset3DTuple, calculate_std_dev_manual, ObservableObject, get_verbose_logger
from autotrainer.core.configuration.behavior_configuration import ShiftXYZBufferHandlerConfig
from autotrainer.core.diamond_triangle_config import DiamondTriangleOffsetConfig
from autotrainer.inference.analysis import IntersessionResponse


logger = get_verbose_logger(__name__)

ProcessedShiftXYZCallbackHandlerT = Optional[Callable[[Offset3DTuple], None]]


class ShiftXYZBaseHandler(abc.ABC):

    def reset(self):
        """Ensure cleared state"""

    def __call__(
        self, rsp: IntersessionResponse, *, reduce_method=statistics.median
    ) -> Optional[Offset3DTuple]:
        """Process/accumulate one intersession response,
        return None if the response does not generate yet a full shift XYZ result"""

    def make_shift_from_rh_list(self, rh_list: List[Offset3DTuple]) -> Offset3DTuple:
        """Compute the full shift from an entire RH max vp list"""


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

    def __call__(self, rsp: IntersessionResponse, *, reduce_method=statistics.median):
        current_buffer = self._failed_reaches_buffer
        current_buffer.extend(rsp.rh_max_vp_list)
        cfg = self._config
        if len(current_buffer) < cfg.minimum_reach_fail:
            return None
        shift = self.make_shift_from_rh_list(current_buffer)
        current_buffer.clear()
        return shift

    def make_shift_from_rh_list(self, rh_list: List[Offset3DTuple]) -> Offset3DTuple:
        if len(rh_list) == 0:
            return Offset3DTuple.get_nan()
        cfg = self._config
        if len(rh_list) == 1:
            mean_off = rh_list[0]
            stdev_off = Offset3DTuple.get_zero()
        else:
            mean_off, stdev_off = calculate_std_dev_manual(rh_list, reduce_method=statistics.median)
        #
        target = Offset3DTuple(cfg.target.x, cfg.target.y, cfg.target.z)
        #
        off_x, off_y, off_z = mean_off - target
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


class ShiftXYZHandler(ObservableObject):

    LAST_SHIFT_XYZ = "last_shift_xyz"
    LAST_PROCESSED_SHIFT_XYZ = "last_processed_shift_xyz"

    def __init__(self):
        super().__init__()
        default_handler = ShiftXYZBufferHandler(config=ShiftXYZBufferHandlerConfig())
        self._result_handler: ShiftXYZBaseHandler = default_handler
        self._processed_shift_handler: ProcessedShiftXYZCallbackHandlerT = None
        self._last_shift_xyz: Optional[Offset3DTuple] = None
        self._last_processed_shift_xyz: Optional[Offset3DTuple] = None

    def reset(self):
        self._result_handler.reset()
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
    def handler(self) -> Optional[ShiftXYZBaseHandler]:
        return self._result_handler

    def set_handler(self, handler: ShiftXYZBaseHandler):
        self._result_handler = handler

    def set_processed_handler(self, func: ProcessedShiftXYZCallbackHandlerT):
        self._processed_shift_handler = func

    def put_intersession_response(self, trial_result: IntersessionResponse):
        trial_shift = self._result_handler.make_shift_from_rh_list(trial_result.rh_max_vp_list)
        self.last_shift_xyz = trial_shift
        processed_shift = self._result_handler(trial_result)
        if processed_shift is not None:
            self.last_processed_shift_xyz = processed_shift
            func = self._processed_shift_handler
            if func is None:
                logger.debug("handle_processed_shift_func undefined")
            else:
                func(processed_shift)  # noqa
                # not sure why need noqa otherwise PyCharm think it's None, despite the previous if :/
