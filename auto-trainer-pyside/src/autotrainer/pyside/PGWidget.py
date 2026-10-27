from typing import List, Tuple, Optional

import numpy
from pyqtgraph import PlotWidget
import pyqtgraph as pg

pg.ViewBox.suggestPadding = lambda *_: 0.02


PlotXYValues = List[Tuple[float, float]]


class PGWidget(PlotWidget):

    x_window_size = 10  # how long is the rolling window on X axis.
    x_loop_back: Optional[float] = 60  # if not None, how far to go into X before reset to first(0).

    def __init__(self, parent=None):
        super().__init__(
            parent=parent,
            axisItems={"top": pg.AxisItem(orientation="top", showValues=False),
                       "right": pg.AxisItem(orientation="right", showValues=False)})
        self.x = []
        self.y = []
        self._cache: PlotXYValues = []
        self._replace = False
        self._x_first: Optional[float] = None  # to put/use first X value as zero-reference.
        pen = pg.mkPen(color=(0, 0, 255), width=1)
        self._pen = pen
        self._data_line = self.plot(self.x, self.y, pen=pen)

    def reset(self, default=0, length=0):
        self.x = []
        self.y = []
        self._x_first = 0
        for idx in range(length):
            self.x.append(idx)
            self.y.append(default)
        self._data_line.setData(self.x, self.y)

    def replace(self, values: PlotXYValues):
        """Completely replace current set of data with given values"""
        self._replace = False
        if len(values) < 1:
            return
        x_f = self._x_first = values[0][0]
        x = []
        x_add = x.append
        y = []
        y_add = y.append
        for xv, yv in values:
            x_add(xv - x_f)
            y_add(yv)
        self._data_line.setData(x, y)
        self.x = x
        self.y = y

    def update_plot(self, values: PlotXYValues):
        if len(values) < 1:
            return
        x_f = self._x_first
        if x_f is None:
            x_f = values[0][0]
        x_add = self.x.append
        y_add = self.y.append
        for xv, yv in values:
            x_add(xv - x_f)
            y_add(yv)
        x = numpy.asarray(self.x)
        x_last = x[-1]
        idx = numpy.argmax(x_last - x <= self.x_window_size)
        if idx > 0:
            x = x[idx:]
            del self.y[:idx]
        loop_back = self.x_loop_back
        if loop_back is not None and x[0] > loop_back:
            self._x_first = x_f + x[0]
            x -= x[0]
        self.x = x.tolist()
        self._data_line.setData(self.x, self.y)

    def cache_data(self, values: PlotXYValues):
        if len(values) < 1:
            return
        x_f = self._x_first
        if x_f is None:
            self._x_first = values[0][0]
        self._cache.extend(values)

    def replace_cache(self, values: PlotXYValues):
        self._cache = values
        self._replace = True

    def use_cache(self):
        if len(self._cache) > 0:
            values = self._cache
            self._cache = []
            if self._replace:
                self.replace(values)
            else:
                self.update_plot(values)
