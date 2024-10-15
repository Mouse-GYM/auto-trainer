import uuid

from autotrainer.core import ObservableObject


class MockPelletDelivery(ObservableObject):
    """
    Provides both pellet command and reader interfaces for testing.
    """
    def __init__(self):
        super().__init__(event_names=("ack_received",))

        self._last_token = None

    def load_pellet(self):
        self._last_token = uuid.uuid4()
        return self._last_token

    def send_pellet(self):
        self._last_token = uuid.uuid4()
        return self._last_token

    def release_pellet(self):
        self._last_token = uuid.uuid4()
        return self._last_token

    def send_ack(self):
        self.ack_received(self._last_token)
