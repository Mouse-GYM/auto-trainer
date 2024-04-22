class IDeviceListener:
    def connect(self):
        pass

    def disconnect(self):
        pass

    def notify_data(self, data: bytes):
        pass

    def notify_message(self, kind: int, context: object):
        pass
