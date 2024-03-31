from PySide6.QtWidgets import QGridLayout, QLabel, QLineEdit, QWidget, QPushButton


class FoodDeliveryContent(QGridLayout):
    def __init__(self):
        super().__init__()

        self.setContentsMargins(10, 10, 10, 10)

        self.addWidget(QLabel("Food Delivery UART:"))

        uart_id = QLineEdit()
        self.addWidget(uart_id, 0, 1)

        button = QPushButton("Deliver")
        self.addWidget(button, 0, 2)

        self.addWidget(QWidget(), 0, 3)
        self.setColumnStretch(3, 1)
