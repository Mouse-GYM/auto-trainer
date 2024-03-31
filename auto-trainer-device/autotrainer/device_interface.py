class IDeviceInterface:
    def open(self):
        pass

    def close(self):
        pass

    def can_read(self) -> bool:
        pass

    def read(self) -> bytes:
        pass

    def write(self, value: bytes) -> int:
        pass

    def write_str(self, value: str) -> int:
        pass
