import time
from threading import Thread
from datetime import datetime
from queue import Queue, Empty
from typing import Optional, List, Any

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.project import ProjectInfo

from .event_info import EventInfo
from .event_manager_plugin import EventManagerPlugin
from .file_event_plugin import FileEventPlugin
from .logger_event_plugin import LoggerEventPlugin

logger = get_verbose_logger(__name__)


class EventManager:
    """
    Events, in the context of the autotrainer local application, are a set of messages that track specific changes and
    actions of interest.  They are a subset of information that is likely to be logged overall, and are made to conform
    to a specific structure for reading in conjunction with data files during analysis.

    By default, events are also sent to the default logger.  It is generally not necessary to post an event _and_ send
    the same information explicitly to the logger.

    Repeat behavior:  The objective with repeat events (same event without interruption of another event type) is to
    * Immediately output the first instance of the event (as would normally happen)
    * When a new event type is received, output the number of repeats (not counting that first instance already output)
      * Per the first bullet, this new event type will also be immediately output
    """

    _instance: "EventManager"

    @staticmethod
    def _remove_cls_instance():
        try:
            del EventManager._instance
        except AttributeError:
            pass

    @staticmethod
    def default() -> "EventManager":
        """
        Creates (if needed) and returns the default instance.
        """
        cls = EventManager
        if not hasattr(cls, "_instance"):
            instance = cls("EventManagerInstance")
            instance.register_plugin(LoggerEventPlugin())
            instance.register_plugin(FileEventPlugin())
            cls._instance = instance
        return cls._instance

    @staticmethod
    def try_close_default():
        """
        Close the default instance if it exists.  Do not spin one up just to check (e.g.,
        EventManager.default().close() if one was never created).
        """
        cls = EventManager
        cls_inst = getattr(cls, "_instance", None)
        if cls_inst is not None:
            cls_inst.close()
            cls._remove_cls_instance()

    def __del__(self):
        # in case of
        cls_inst = getattr(EventManager, "_instance", None)
        if cls_inst is self:
            self.try_close_default()
        else:
            self.close()

    def __init__(self, key=""):
        if key != "EventManagerInstance":
            raise Exception("Use EventManager.default() to access and instance.")

        self._plugins: List[EventManagerPlugin] = []

        self._project_info = None

        self._last_event_info: Optional[EventInfo] = None
        self._repeat_event_count = 0

        # Callers should expect requests to post an event return as quickly as possible.  Events are pushed to a queue
        # so that processing can be done in a separate thread as resources allow.
        self._write_queue = Queue()
        self._write_thread = Thread(
            target=self._process_queue,
            name=f"{self.__class__.__name__}",
            daemon=True,  # allow the main thread/process to exit even if this thread is still alive
        )
        self._write_thread.start()

    @property
    def is_valid(self):
        return self._write_thread is not None and self._write_queue is not None

    @property
    def project(self) -> ProjectInfo:
        return self._project_info

    @project.setter
    def project(self, value: ProjectInfo) -> None:
        """
        ProjectInfo is an optional property.  If set, it is used to generate the location and name of the event file in
        the expected format.

        Args
            value: ProjectInfo object.  This is used to determine the location of the event file.
        """
        self._project_info = value

        for plugin in self._plugins:
            plugin.set_project(value)

    @property
    def plugins(self) -> List[EventManagerPlugin]:
        # Do not let callers modify ths list. register/unregister are available for this.  This is already dangerous
        # enough - giving them access to the plugins themselves.
        return self._plugins.copy()

    def register_plugin(self, plugin: EventManagerPlugin) -> None:
        """
        Registers a plugin with the event manager.

        Args:
            plugin: The plugin to register.
        """
        if plugin not in self._plugins:
            self._plugins.append(plugin)
            plugin.set_project(self.project)

    def unregister_plugin(self, plugin: EventManagerPlugin) -> None:
        """
        Unregisters a plugin with the event manager.

        Args:
            plugin: The plugin to unregister.
        """
        if plugin in self._plugins:
            self._plugins.remove(plugin)
            # Even though the caller must have a reference to the plugin, take responsibility to close, if needed.
            # In the future, there may be a way to unregister by some kind of key/type/identifier that doesn't require
            # explicit access to the plugin instance by the caller.
            plugin.close()

    def flush(self):
        for plugin in self._plugins:
            plugin.flush()

    def close(self):
        """
        Closes the event manager.  This is required to stop any internal threads and allow a clean exit.  This should
        only be called when the application or script is closing or otherwise finished with the event manager as an
        instance, including the `default` cannot be restarted.
        """
        cls_inst = getattr(EventManager, "_instance", None)
        for plugin in self._plugins:
            plugin.set_enable(False)
        wt = self._write_thread
        wq = self._write_queue
        if wt is not None:
            if wq is not None:
                wq.put(None)
            wt.join()
            self._write_thread = None
        # queue needs be flushed so that we can join it:
        if wq is not None:
            self._write_queue = None  # set it directly, so that no other thread can now put through this instance
            while True:
                try:
                    item = wq.get_nowait()
                    logger.warning("dropped unhandled %s: %s", type(item), item)
                    wq.task_done()
                except Empty:
                    break
            wq.join()
        if cls_inst is self:
            self._remove_cls_instance()

    def post_event_content(self, kind: int, data: Optional[Any] = None, when: Optional[datetime] = None,
                           index: int = None):
        """
        Add an event info instance to the event manager output queue.  This is a convenience method that creates an
        EventInfo object and optionally populates timestamp related fields as the time this method is called.  If timing
        information is critical, those arguments should be explicitly set, or `post_event()` should be used with a
        preconstructed `EventInfo` instance with the desired timestamp fields.

        Args:
            kind: See EventInfo.kind for a detailed description.
            data: See EventInfo.kind for a detailed description.
            when: See EventInfo.kind for a detailed description.
            index: See EventInfo.kind for a detailed description.

        """
        info = EventInfo(kind,
                         when=datetime.now() if when is None else when,
                         index=time.perf_counter_ns() if index is None else index,
                         context=data)

        self.post_event(info)

    def post_event(self, info: EventInfo):
        """
        Posts an event info instance to the event manager.

        Args:
            info:

        Returns:

        """
        if info is None:
            # "~paranoid" check but that will prevent the non-desired stop of the work thread.
            raise RuntimeError("post_event(None) refused")
        wq = self._write_queue
        if wq is None:
            logger.debug("post_event(%s) but write queue already removed", info.kind)
        else:
            wq.put(info)

    def has_pending(self) -> bool:
        """
        This is primarily for testing and diagnostics.  It should not be relied upon absolutely as this class will not
        guarantee that whatever implementation is used to queue events for processing will accurately report the state
        of empty at all times.

        Returns: True if there are pending events to process by the handlers.  Might be accurate, might not.
        """
        wq = self._write_queue
        if wq is None:
            return False
        return not wq.empty()

    def _process_queue(self):
        # Because we a) use plugins and b) allow for EventInfo->is_same to be overridden, we may be given a plugin that
        # errors on every process_event, or an EventInfo that errors on every is_same.  This would bury the log if we
        # reported it every time.  It may also be a one time error for the plugin, so we don't want to just skip/remove
        # if there is an error.
        # This will log the first occurrence of each of the above, but not spam the log if it is a recurring issue.

        is_same_error_reported = False
        process_event_error_reported = False

        while True:
            try:
                # Workaround or current Jetson behavior w/ queue.get(timeout=).
                info = self._write_queue.get(timeout=0.5)
                if info is None:
                    logger.verbose("got exit sentinel, exiting main loop")
                    self._write_queue.task_done()
                    break
            except Empty:
                continue

            if not isinstance(info, EventInfo):
                logger.warning("unexpected event info instance")
                self._write_queue.task_done()
                continue

            try:
                is_same = info.is_same(self._last_event_info)
            except Exception as err:  # Possibly coming from EventInfo subclass - cannot predict type of error.
                if not is_same_error_reported:
                    logger.error("is_same failed: %s", err)
                    is_same_error_reported = True
            else:
                if is_same:
                    self._repeat_event_count += 1
                    self._write_queue.task_done()
                    continue

            try:
                if self._repeat_event_count > 0:
                    self._process_event(self._last_event_info, self._repeat_event_count)
                    self._repeat_event_count = 0

                self._last_event_info = info
                self._process_event(info)
            except Exception as err:  # Coming from an arbitrary plugin process_event() - cannot predict type of error.
                # TODO (maybe): track exceptions per plugin.  After some number N exceptions, disable the plugin.
                if not process_event_error_reported:
                    logger.exception("process queue info (%s) failed: %s", info, err)
                    process_event_error_reported = True

            self._write_queue.task_done()

        for plugin in self._plugins:
            plugin.close()

    def _process_event(self, info: EventInfo, repeat_count: int = 0):
        for plugin in self._plugins:
            logger.spam("plugin %s: processing event %s", plugin, info)
            plugin.process_event(info, repeat_count)
