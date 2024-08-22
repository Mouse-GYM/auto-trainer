from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QSurfaceFormat, QBrush, QPixmap, QPen
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget, QGraphicsView, QGraphicsScene, QHBoxLayout, QGraphicsPixmapItem, \
    QGraphicsEllipseItem

class ATGLImageView(QWidget):
    def __init__(self, width: int = 450, height: int = 300):
        super().__init__()

        self._width = float(width)
        self._height = float(height)

        self._width_factor = 1
        self._height_factor = 1

        self._scene = QGraphicsScene(0, 0, width, height)

        brush = QBrush(Qt.GlobalColor.white)
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

        pen = QPen(Qt.GlobalColor.red)
        brush = QBrush(Qt.GlobalColor.red)
        pen.setWidth(1)
        self._pellet_point = QGraphicsEllipseItem(0, 0, 5, 5)
        self._pellet_point.setPen(pen)
        self._pellet_point.setBrush(brush)
        self._pellet_point.setZValue(100)
        self._pellet_point.setPos(-10, -10)

        self._scene.addItem(self._pellet_point)

        pen = QPen(Qt.GlobalColor.magenta)
        brush = QBrush(Qt.GlobalColor.magenta)
        pen.setWidth(1)
        self._star_point = QGraphicsEllipseItem(0, 0, 5, 5)
        self._star_point.setPen(pen)
        self._star_point.setBrush(brush)
        self._star_point.setZValue(100)
        self._star_point.setPos(-10, -10)

        self._scene.addItem(self._star_point)

        self._pixmap = None

        layout = QHBoxLayout()
        layout.addWidget(view)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self._count = 0

    def set_data_size(self, width, height):
        scale = self._height / height
        self._width_factor = width * scale
        self._height_factor = height * scale

        self._pixmap = None

    def set_data(self, image: QImage):
        if self._pixmap is None:
            self._pixmap = QGraphicsPixmapItem(QPixmap.fromImage(image))
            self._pixmap.setZValue(0)
            self._pixmap.setPos(0, 0)
            self._scene.addItem(self._pixmap)
        else:
            self._pixmap.setPixmap(QPixmap.fromImage(image))

    def set_points(self, point):
        self._pellet_point.setPos(point[0] * self._width_factor, point[1] * self._height_factor)
        self._star_point.setPos(point[2] * self._width_factor, point[3] * self._height_factor)
