from pyqtgraph import PlotWidget
import pyqtgraph as pg

pg.ViewBox.suggestPadding = lambda *_: 0.02


class PGWidget(PlotWidget):
    def __init__(self):
        super().__init__(axisItems={"top": pg.AxisItem(orientation="top", showValues=False),
                                    "right": pg.AxisItem(orientation="right", showValues=False)})

        self.x = []
        self.y = []

        self.scale_x = 1

        pen = pg.mkPen(color=(0, 0, 255), width=1)
        self._data_line = self.plot(self.x, self.y, pen=pen)

        self._cache = list()

    def reset(self):
        self.x = []
        self.y = []
        self._data_line.setData(self.x, self.y)

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

        first_x = -1 if len(self.x) == 0 else int(self.x[-1] * self.scale_x)

        x_list = list(range(first_x + 1, first_x + add_len + 1))

        if self.scale_x != 1:
            x_list_2 = [float(x) / self.scale_x for x in x_list]
        else:
            x_list_2 = x_list

        self.x.extend(x_list_2)
        self.y.extend(values)

        self._data_line.setData(self.x, self.y)

    def cache_data(self, values):
        self._cache += values

    def use_cache(self):
        if len(self._cache) > 0:
            values = self._cache
            self._cache = list()
            self.update_plot(values)
