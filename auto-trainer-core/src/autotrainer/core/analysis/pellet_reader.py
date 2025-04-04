import logging
from queue import Queue

from .system_message_handler import SystemMessageHandler

logger = logging.getLogger(__name__)


class PelletReader(SystemMessageHandler):
    def __init__(self, input_queue: Queue):
        super().__init__(input_queue)

        logger.warning("PelletReader is deprecated. Use SystemMessageHandler instead.")
