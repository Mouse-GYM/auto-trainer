from .device_api import DeviceApi


class Device:
    """Defines the required methods to represent a device."""

    def __init__(self, api: DeviceApi = None):
        self._api = api

    def connect(self):
        pass

    def disconnect(self):
        pass

    def notify_data(self, data: bytes) -> None:
        """Notification for data received from the device

        :param data: one or more bytes received from the device to be handled/interpreted by this Device instance
        """
        pass

    def notify_message(self, kind: int, data: object, context: object = None) -> None:
        """Notification for messages received from the client script or application

        A set of message kind values and any expected associated data are typically defined by specific Device subclass
        implementation.  Context is an optional argument whose value is returned to the caller when the action taken by
        the message kind is complete.  For example, if the action is to send data to the physical device and received a
        response, the context will be returned as part of the DeviceApi message_callback.

        :param kind: A value whose interpretation will be Device dependent
        :param data: Any additional data required for the message beyond the kind
        :param context: A value to be returned to caller upon completion of the message
        """
        pass

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        self._api = value
