import logging
import time
from queue import Queue, Empty
from threading import Thread
from typing import Callable

from autotrainer.core.logging import get_verbose_logger
from ..observable_object import ObservableObject

from .system_status_message import SystemStatusMessageKind

logger = get_verbose_logger(__name__)

TERMINATE = -1001


class MessageHandler(ObservableObject):
    """
    Base class for handling messages that come from the hardware.  It has two primary purposes.

    The first is to ensure that any middle-management of information or data happens in a separate thread from both the
    hardware interfacing and any downstream consumers without requiring either the hardware code or the downstream code
    to know whether that is taken care of or not - other than knowing to call start() on this object when ready to
    receive messages.

    The second is to insulate downstream consumers from any specifics of the hardware implementation such as how
    commands are acknowledged, what capabilities different versions of the hardware may have, etc.  Subclasses for
    elements such as pellet delivery, tunnel behavior, and sensor measurements present properties (with change
    notification), callbacks, and other means of making the data available in a consistent format that downstream
    consumers care about rather than as specifically implemented the hardware.
    """
    FIRMWARE_VERSION_PROPERTY = "firmware_version"

    HEAD_MAGNET_INTENSITY_PROPERTY = "head_magnet_intensity"
    HEAD_GATE_PROPERTY = "gate_angle"

    DEVICE_X_PROPERTY = "device_x"
    DEVICE_Y_PROPERTY = "device_y"
    DEVICE_Z_PROPERTY = "device_z"

    LOAD_ARM_ANGLE_PROPERTY = "load_angle"
    COVER_ARM_ANGLE_PROPERTY = "cover_angle"

    FRONT_DOOR_PROPERTY = "front_door"
    DRAWER_DOOR_PROPERTY = "drawer_door"
    SPARE_DOOR_PROPERTY = "spare_door"
    EXT_BUTTON_PROPERTY = "ext_button"

    STIMULI_PROPERTY = "stimuli"
    CONFIG_PROPERTY = "config"

    # type hints helper:
    # dynamic event:
    ack_received: Callable[[str], None]

    def __init__(self, input_queue: Queue, name: str = "message-handler", event_names=()):
        super().__init__(event_names=event_names + ("ack_received",))
        self._input_queue = input_queue
        self._name = name
        self._current_thread = None

    def __del__(self):
        thread = self._current_thread
        if thread is not None:
            self.request_terminate()

    @property
    def input_queue(self) -> Queue:
        return self._input_queue

    def start(self):
        if self._current_thread is None or not self._current_thread.is_alive():
            logger.verbose("Starting system message handler thread")
            self._current_thread = Thread(
                target=self.run, name=self.__class__.__name__,
                daemon=True,  # in case main thread exits: also have the current handler thread to exit
            )
            self._current_thread.start()

    def run(self):
        logger.debug(f"<{self._name}>: entering message event loop")
        q_get = self._input_queue.get
        task_done = self._input_queue.task_done
        msg_received = self.message_received
        tot_read_count = 0
        t_next_check_size = time.time()
        while True:
            msg, data = q_get()
            if __debug__:
                tot_read_count += 1
                t_now = time.time()
                if t_now > t_next_check_size:
                    logger.debug("system message handler input queue: size=%s read=%.1f / s",
                                 self._input_queue.qsize(), tot_read_count / 60)
                    t_next_check_size += 60
                    tot_read_count = 0
            if msg == TERMINATE:
                task_done()
                break
            elif msg == SystemStatusMessageKind.ACKNOWLEDGE:
                try:
                    self.ack_received(data)
                except Exception as err:
                    logger.exception("Error during ack_received callback: %s", err)
            elif msg == SystemStatusMessageKind.FIRMWARE_VERSION:
                self.property_changed(MessageHandler.FIRMWARE_VERSION_PROPERTY, data, None)
            else:
                try:
                    msg_received(msg, data)
                except Exception as err:
                    logger.exception("Error during msg_received callback: msg=%s err=%s", msg, err)
            task_done()
        logger.debug(f"<{self._name}>: exiting message event loop")

    def request_terminate(self):
        """
        Sends a termination request to the device reader queue.  The thread may have not yet terminated when this call
        returns.
        """
        if self._input_queue is not None:
            self._input_queue.put((TERMINATE, None))

    def wait_terminated(self):
        thread = self._current_thread
        queue = self._input_queue
        if thread is not None:
            self._current_thread = None
            thread.join()
        if queue is not None:
            self._input_queue = None
            while not queue.empty():
                try:
                    obj = queue.get_nowait()
                except Empty:
                    break
                logger.warning("drop unhandled %s", type(obj))
                queue.task_done()
            queue.join()

    def message_received(self, msg, _data):
        pass
