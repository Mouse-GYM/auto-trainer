from pyqtgraph import PlotWidget
import pyqtgraph as pg


class PGWidget(PlotWidget):
    def __init__(self):
        super().__init__()

        self.x = []
        self.y = []

        pen = pg.mkPen(color=(0, 0, 255), width=1)
        self._data_line = self.plot(self.x, self.y, pen=pen)

        self._cache = list()

    def update_plot(self, values):
        add_len = len(values)

        if add_len >= 500:
            self.x = []
            self.y = []
            values = values[add_len - 500:]
            add_len = len(values)
        elif len(self.x) + add_len > 500:
            self.x = self.x[add_len:]
            self.y = self.y[add_len:]

        first_x = -1 if len(self.x) == 0 else self.x[-1]

        self.x.extend(list(range(first_x + 1, first_x + add_len + 1)))
        self.y.extend(values)

        self._data_line.setData(self.x, self.y)

    def cache_data(self, values):
        self._cache += values

    def use_cache(self):
        if len(self._cache) > 0:
            values = self._cache
            self._cache = list()
            self.update_plot(values)
