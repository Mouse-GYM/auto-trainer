from PySide6.QtWidgets import QGridLayout, QLabel, QComboBox, QLineEdit, QPushButton


class AnalysisContent(QGridLayout):
    def __init__(self):
        super().__init__()

        self.setContentsMargins(10, 10, 10, 10)

        self.setRowStretch(3, 1)

        self.setColumnStretch(1, 1)

        self.addWidget(QLabel("Analysis:"), 0, 0)

        combobox = QComboBox()
        combobox.addItem("None")
        combobox.addItem("Deferred")
        combobox.addItem("Real-time")

        self.addWidget(combobox, 0, 1)

        self.addWidget(QLabel("Model:"), 1, 0)

        self.addWidget(QLineEdit(), 1, 1)

        self.addWidget(QPushButton("..."), 1, 2)

        self.addWidget(QLabel("Algorithm:"), 2, 0)

        self.addWidget(QLineEdit(), 2, 1)
