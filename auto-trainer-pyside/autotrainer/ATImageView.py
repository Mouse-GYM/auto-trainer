from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel


class ATImageView(QLabel):
    def __init__(self, data: bytearray = None, width: int = 0, height: int = 0):
        super().__init__()

        if data is not None:
            image = QImage(data, width, height, QImage.Format_Grayscale8)
            self.set_data(image)

    def set_data(self, image: QImage):
        self.setPixmap(QPixmap.fromImage(image))
