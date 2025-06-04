import warnings
from typing import List, Optional, Dict

import numpy
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
        self._raw_img_scale_w = self._raw_img_scale_h = 1
        self._raw_img_w = self._width
        self._raw_img_h = self._height

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
        self._cur_image = None  # image must remain active to prevent segfault when pixmap continue use it.

        layout = QHBoxLayout()
        layout.addWidget(view)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self._count = 0
        self._pose_algo: Optional[PoseAlgorithm] = None

    def set_pose_algo(self, pose_algo: PoseAlgorithm):
        self._pose_algo = pose_algo

    def set_data_size(self, width, height):
        # data size is the output model resolution
        self._pixmap = None
        self._data_width = width
        self._data_height = height
        self._width_factor = self._data_width / self._width
        self._height_factor = self._data_height / self._height

    def set_scale_aspect_ratio(self, scale_w, scale_h):
        # used when source image is not same aspect ratio than the one used by self
        self._raw_img_scale_w = scale_w
        self._raw_img_scale_h = scale_h

    def set_data(self, image: QImage):
        # retain a ref the used image to keep it alive after calling function also return
        self._cur_image = image
        pixmap = QPixmap.fromImage(image)
        if self._pixmap is None:
            self._pixmap = QGraphicsPixmapItem(pixmap)
            self._pixmap.setZValue(0)
            self._pixmap.setPos(0, 0)
            self._scene.addItem(self._pixmap)
        else:
            self._pixmap.setPixmap(pixmap)

    def set_points(self, points: List[PoseTuple]):
        pose_algo = self._pose_algo
        if pose_algo is None:
            return
        width_f = self._raw_img_scale_w / self._width_factor
        height_f = self._raw_img_scale_h / self._height_factor
        # values are in coordinates (self._data_width, self._data_height)
        for elem, point in self._points.items():
            values = points[pose_algo.get_part_index(elem)]
            x = values[0] * width_f
            y = values[1] * height_f
            if x < 0 or y < 0 or x > self._width or y > self._height:
                point.setVisible(False)
            else:
                point.setPos(x, y)
                point.setVisible(True)
