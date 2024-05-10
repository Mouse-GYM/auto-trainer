class IDeviceInterface:
    """ Defines the required methods for a class that provides low-level communication with a device, such as serial"""
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
