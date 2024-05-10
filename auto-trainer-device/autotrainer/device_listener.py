class IDeviceListener:
    """Defines the required methods to represent a device."""
    def connect(self):
        pass

    def disconnect(self):
        pass

    def notify_data(self, data: bytes):
        """Notification for data received from the device"""
        pass

    def notify_message(self, kind: int, data: object, content: object):
        """Notification for messages received from the client script or application"""
        pass
