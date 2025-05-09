import logging
import uuid

from autotrainer.core import ObservableObject

logger = logging.getLogger(__name__)


class MockPelletDelivery(ObservableObject):
    """
    Provides both pellet command and reader interfaces for testing.
    """

    def __init__(self):
        super().__init__(event_names=("ack_received",))

        self._last_token = None

    def send_home(self):
        self._last_token = uuid.uuid4()
        logger.debug("home")
        return self._last_token

    def load_pellet(self):
        self._last_token = uuid.uuid4()
        logger.debug("load")
        return self._last_token

    def send_pellet(self):
        self._last_token = uuid.uuid4()
        logger.debug("send")
        return self._last_token

    def release_pellet(self):
        self._last_token = uuid.uuid4()
        logger.debug("release")
        return self._last_token

    def cover_pellet(self):
        self._last_token = uuid.uuid4()
        logger.debug("cover")
        return self._last_token

    def send_ack(self):
        self.ack_received(self._last_token)

    def set_x(self, value, *, absolute=True):
        pass

    def set_y(self, value, *, absolute=True):
        pass

    def set_z(self, value, *, absolute=True):
        pass
