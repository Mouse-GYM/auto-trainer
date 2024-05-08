from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QSurfaceFormat, QBrush, QPixmap
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget, QGraphicsView, QGraphicsScene, QHBoxLayout, QGraphicsPixmapItem


class ATGLImageView(QWidget):
    def __init__(self, data: bytearray = None, width: int = 450, height: int = 300):
        super().__init__()

        self._scene = QGraphicsScene(0, 0, width, height)

        brush = QBrush(Qt.GlobalColor.white)
        self._scene.setBackgroundBrush(brush)

        self._widget = QOpenGLWidget()
        view = QGraphicsView(self._scene)
        view.setStyleSheet("border: 0px")

        sformat = QSurfaceFormat()
        sformat.setSamples(4)
        self._widget.setFormat(sformat)
        view.setViewport(self._widget)
        view.setFixedSize(width, height)
        view.setContentsMargins(0, 0, 0, 0)

        self._pixmap = None

        layout = QHBoxLayout()
        layout.addWidget(view)
        self.setLayout(layout)

        if data is not None:
            image = QImage(data, width, height, QImage.Format_Grayscale8)
            self.set_data(image)

    def set_data(self, image: QImage):
        if self._pixmap is None:
            self._pixmap = QGraphicsPixmapItem(QPixmap.fromImage(image))
            self._pixmap.setPos(0, 0)
            self._scene.addItem(self._pixmap)
        else:
            self._pixmap.setPixmap(QPixmap.fromImage(image))
