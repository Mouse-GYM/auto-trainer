import abc
import os
import math
import statistics
from typing import Callable, Optional, List, Union

from autotrainer.core import Offset3DTuple, calculate_std_dev_manual, ObservableObject, get_verbose_logger
from autotrainer.core.configuration.behavior_configuration import ShiftXYZBufferHandlerConfig
from autotrainer.inference.analysis import IntersessionResponse


logger = get_verbose_logger(__name__)

ProcessedShiftXYZCallbackHandlerT = Optional[Callable[[Offset3DTuple], None]]



class ShiftXYZBaseHandler(abc.ABC):

    def reset(self):
        """Ensure cleared state"""

    def __call__(
        self, rsp: IntersessionResponse, *, reduce_method=statistics.median
    ) -> Optional[Offset3DTuple]:
        """Process one intersession response"""


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
        mean_off, stdev_off = calculate_std_dev_manual(current_buffer, reduce_method=reduce_method)
        logger.verbose("ShiftXYZBuffer mean/stdev: %s / %s ; buffer=%s",
                       mean_off, stdev_off, [o.round(1) for o in current_buffer])
        self._failed_reaches_buffer.clear()
        target = Offset3DTuple(cfg.target_x, cfg.target_y, cfg.target_z)
        off_x, off_y, off_z = target - mean_off
        shift_x = off_x if abs(off_x) > 0.5 else 0
        shift_y = off_y if abs(off_y) > 0.5 else 0
        shift_z = off_z if abs(off_z) > 0.5 else 0
        return Offset3DTuple(shift_x, shift_y, shift_z)


class ShiftXYZHandler(ObservableObject):

    LAST_SHIFT_XYZ = "last_shift_xyz"
    LAST_PROCESSED_SHIFT_XYZ = "last_processed_shift_xyz"

    def __init__(self):
        super().__init__()
        default_handler = ShiftXYZBufferHandler(config=ShiftXYZBufferHandlerConfig())
        self._intersession_response_handler: ShiftXYZBaseHandler = default_handler
        self._processed_shift_handler: ProcessedShiftXYZCallbackHandlerT = None
        self._last_shift_xyz: Optional[Offset3DTuple] = None
        self._last_processed_shift_xyz: Optional[Offset3DTuple] = None

    def reset(self):
        self._intersession_response_handler.reset()
        self.last_processed_shift_xyz = self.last_shift_xyz = Offset3DTuple(math.nan, math.nan, math.nan)

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
    def last_processed_shift_xyz(self, value):
        prev, self._last_processed_shift_xyz = self.last_processed_shift_xyz, value
        # use property_changed, which always call the property changed callbacks, even if same value than prev:
        self.property_changed(self.LAST_PROCESSED_SHIFT_XYZ, value, prev)

    #

    @property
    def handler(self) -> Optional[ShiftXYZBaseHandler]:
        return self._intersession_response_handler

    def set_handler(self, handler: ShiftXYZBaseHandler):
        self._intersession_response_handler = handler

    def set_processed_handler(self, func: ProcessedShiftXYZCallbackHandlerT):
        self._processed_shift_handler = func

    def put_intersession_response(self, res: IntersessionResponse):
        if len(res.rh_max_vp_list) == 0:
            return
        if len(res.rh_max_vp_list) > 1:
            shift, stdev = calculate_std_dev_manual(res.rh_max_vp_list, reduce_method=statistics.median)
        else:
            shift = res.rh_max_vp_list[0]
        self.last_shift_xyz = shift
        res = self._intersession_response_handler(res)
        if res is not None:
            self.last_processed_shift_xyz = res
            func = self._processed_shift_handler
            if func is None:
                logger.debug("handle_processed_shift_func undefined")
            else:
                func(res)  # noqa
                # not sure why need noqa otherwise PyCharm think it's None, despite the previous if :/
