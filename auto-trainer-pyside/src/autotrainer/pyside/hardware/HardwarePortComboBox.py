from PySide6.QtWidgets import QComboBox


class HardwarePortComboBox(QComboBox):
    def __init__(self, ports: list = None, port: str = None):
        super().__init__()

        self._port = port
        self._ports = ports

        self.refresh_ports(ports)

    @property
    def port(self):
        return self._port

    @port.setter
    def port(self, port: str):
        self._port = port

    def refresh_ports(self, ports: list = None):
        self.blockSignals(True)
        self.clear()
        self.blockSignals(False)

        self._ports = ports

        if ports is None or len(ports) == 0:
            return

        self.blockSignals(True)
        for idx, port in enumerate(ports):
            self.addItem(port)
        self.blockSignals(False)

        self.select_port(self._port)

    def select_port(self, port: str = None):
        self._port = port

        if port is None or len(port) == 0:
            self.setCurrentIndex(-1)
            return

        if port not in self._ports:
            self._ports.append(port)
            self.addItem(port)

        self.setCurrentIndex(self._ports.index(port))
