import warnings
from typing import List, Optional, Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QSurfaceFormat, QBrush, QPixmap, QPen
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget, QGraphicsView, QGraphicsScene, QHBoxLayout, QGraphicsPixmapItem, \
    QGraphicsEllipseItem

from autotrainer.inference import PoseTuple, PoseAlgorithm
from autotrainer.inference.pose_elements import SceneElement


class QGLImageView(QWidget):
    def __init__(self, width: int = 450, height: int = 300):
        """Image view for a camera, (width, height) is the dimention of the output model"""
        super().__init__()

        self._width = float(width)
        self._height = float(height)

        self._width_factor = 1
        self._height_factor = 1

        self._scene = QGraphicsScene(0, 0, width, height)

        brush = QBrush(Qt.GlobalColor.black)
        self._scene.setBackgroundBrush(brush)

        self._widget = QOpenGLWidget()
        view = QGraphicsView(self._scene)
        view.setStyleSheet("border: 0x")

        sformat = QSurfaceFormat()
        sformat.setSamples(4)
        self._widget.setFormat(sformat)
        view.setViewport(self._widget)
        view.setFixedSize(width, height)
        view.setContentsMargins(0, 0, 0, 0)

        self._points: Dict[SceneElement, QGraphicsEllipseItem] = {}

        def add_managed_point(color, elem):
            point = self._points[elem] = QGraphicsEllipseItem(0, 0, 5, 5)
            pen = QPen(color)
            pen.setWidth(1)
            point.setPen(pen)
            point.setBrush(QBrush(color))
            point.setZValue(100)
            point.setPos(-10, -10)
            self._scene.addItem(point)

        add_managed_point(Qt.GlobalColor.red, SceneElement.Pellet)
        add_managed_point(Qt.GlobalColor.magenta, SceneElement.Star)
        add_managed_point(Qt.GlobalColor.blue, SceneElement.Diamond)
        add_managed_point(Qt.GlobalColor.green, SceneElement.Triangle)
        add_managed_point(Qt.GlobalColor.white, SceneElement.LH_grab)

        self._pixmap = None

        layout = QHBoxLayout()
        layout.addWidget(view)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self._count = 0
        self._pose_algo: Optional[PoseAlgorithm] = None

    def set_pose_algo(self, pose_algo: PoseAlgorithm):
        self._pose_algo = pose_algo

    def set_data_size(self, width, height):
        self._pixmap = None
        self._data_width = width
        self._data_height = height
        scale_w = self._width / self._data_width
        scale_h = self._height / self._data_height
        self._width_factor = scale_w
        self._height_factor = scale_h

    def set_data(self, image: QImage):
        if self._pixmap is None:
            self._pixmap = QGraphicsPixmapItem(QPixmap.fromImage(image))
            self._pixmap.setZValue(0)
            self._pixmap.setPos(0, 0)
            self._scene.addItem(self._pixmap)
        else:
            self._pixmap.setPixmap(QPixmap.fromImage(image))
        # display view is (self._width, self._height)
        # output coordinates are in (self._data_width, self._data_height)
        # image is supposed to also be in same size than display view
        img_size = image.width(), image.height()
        cur_size = self._width, self._height
        if img_size != cur_size:
            raise RuntimeError(f"received image not same size than display view: {img_size} vs {cur_size}")
            # # warnings.warn(f"received image not same size than display view: {img_size} vs {cur_size}", UserWarning)
            # scale_w = self._width / img_size[0]
            # scale_h = self._height / img_size[1]
            # self._width_factor = scale_w
            # self._height_factor = scale_h

    def set_points(self, points: List[PoseTuple]):
        pose_algo = self._pose_algo
        if pose_algo is None:
            return
        width_f = self._width_factor
        height_f = self._height_factor
        for elem, point in self._points.items():
            values = points[pose_algo.get_part_index(elem)]
            point.setPos(values[0] * width_f, values[1] * height_f)
