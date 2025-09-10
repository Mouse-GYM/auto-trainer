from __future__ import annotations

import ctypes
import logging
import multiprocessing as mp
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Tuple, NamedTuple, Union, Optional

from typing_extensions import Self

from autotrainer.core import ValueHolderDescriptor, RawValueHolder
from autotrainer.core.multiproc import get_mp_ctx

DATE_FORMAT = "%Y%m%d"

TIME_FORMAT = "%H%M%S"

MINUTE_INTERVAL_FORMAT = "h%Hm%M"

HOUR_INTERVAL_FORMAT = "h%H"

IMAGE_CAPTURE_SUFFIX = "_images"

logger = logging.getLogger(__name__)


class ProjectInterval(IntEnum):
    NONE = -1
    MINUTE = 0
    HOUR = 1


class ProjectPath(NamedTuple):
    location: str
    prefix: str
    full_path: str


class IntervalSource(NamedTuple):
    location: str
    prefix: str
    interval: int


class SessionSource(NamedTuple):
    location: str
    prefix: str
    session_index: int


class IntervalFileInfo(NamedTuple):
    location: str
    file: str
    current_interval: int


def _safe_ensure_location(location: str) -> bool:
    try:
        path = Path(location)
        path.mkdir(parents=True, exist_ok=True)
    except Exception as err:
        logger.error("Could not create dir %r: %s", location, err)
        return False
    return True


# Windows does not like .mp4 extension when opencv is technically saving to an mkv container.
video_write_ext = "mp4" if sys.platform.startswith("linux") else "mkv"


# NB: so that we can easily patch from test
def _get_datetime_now() -> datetime:
    return datetime.now()


@dataclass
class ProjectInfo:
    """Contains all details needed to uniquely identify a session project.

    The ProjectInfo is used/shared possibly to multiple processes.
    It will only have this multiprocess capability if-and-only-if it's created without specifying the `when` and
     `session` attributes. Or if they are both set to None.
    If `when` is provided but not `session` then `session` defaults to 1.
    Providing `session` but not `when` is an error.
    """

    root: str = ""
    device_id: str = ""
    _when: Union[mp.Value, RawValueHolder] = None
    ensure_exists: bool = False
    camera_1: str = ""
    camera_2: str = ""
    _session: Union[mp.Value, RawValueHolder] = None
    session = ValueHolderDescriptor()

    # custom/overloaded init to allow normal/exact same than previous argument names
    def __init__(
        self,
        root: str=root,
        device_id: str=device_id,
        when: Optional[datetime]=_when,
        ensure_exists: bool=ensure_exists,
        camera_1: str=camera_1,
        camera_2: str=camera_2,
        session: Optional[int]=None,
    ):
        if when is not None:
            when = RawValueHolder(when.timestamp())
            if session is None:
                session = 1
        if session is not None:
            session = RawValueHolder(session)
            if when is None:
                raise ValueError("Cannot create ProjectInfo with session but without when")
        self.root = root
        self.device_id = device_id
        self._when = when
        self.ensure_exists = ensure_exists
        self.camera_1 = camera_1
        self.camera_2 = camera_2
        self._session = session
        super().__init__()
        self.__post_init__()

    def __post_init__(self):
        if self._session is None and self._when is None:
            ctx = get_mp_ctx()
            session_shared_obj = self._session = ctx.Value(ctypes.c_uint32, 1)
            # use the same lock for both session and when mp shared values:
            self._when = ctx.Value(ctypes.c_double,  # double required, not float !!
                                   0,  # 1970-01-01
                                   lock=session_shared_obj.get_lock())

    def __eq__(self, other):
        if isinstance(other, ProjectInfo):
            return (
                self.root == other.root
                and self.device_id == other.device_id
                and self.when == other.when
                and self.camera_1 == other.camera_1
                and self.camera_2 == other.camera_2
                and self.session == other.session
            )
        return super().__eq__(other)

    # for multiprocess capability:
    def __enter__(self):
        if hasattr(self._session, "acquire"):
            self._session.acquire()

    def __exit__(self, ex, ex_type, ex_stack):
        if hasattr(self._session, "acquire"):
            self._session.release()

    @property
    def when(self) -> datetime:
        unix_ts = self._when.value
        return datetime.fromtimestamp(unix_ts)

    @when.setter
    def when(self, value: datetime):
        self._when.value = value.timestamp()

    def is_valid(self):
        return self.root is not None and len(self.root) > 0

    def get_day_path(self, skip_ensure: bool = False, when: Optional[datetime]=None) -> Union[Tuple[str, str], Tuple[None, None]]:
        """Get the location and related datetime for given arguments.
        If when is None then self.when is used, which can eventually be None, in which case now() is used.
        """
        if when is None:
            when = _get_datetime_now() if self.when is None else self.when

        today = when.strftime(DATE_FORMAT)
        location = os.path.join(self.root, today)
        if self.device_id:
            location = os.path.join(location, self.device_id)

        if not skip_ensure and self.ensure_exists:
            if not _safe_ensure_location(location):
                return None, None

        return location, today

    def get_interval(self, interval: ProjectInterval = ProjectInterval.NONE) -> int:
        if interval == ProjectInterval.NONE:
            return -1
        when = self.when if self.when is not None else _get_datetime_now()
        return when.hour if interval == ProjectInterval.HOUR else when.minute

    def get_interval_path(
        self,
        name: str = "",
        interval: ProjectInterval = ProjectInterval.HOUR,
        skip_ensure: bool = False,
        when: Optional[datetime] = None,
    ) -> Optional[IntervalSource]:
        when = (self.when if self.when is not None else _get_datetime_now()) if when is None else when
        time_format = HOUR_INTERVAL_FORMAT if interval == ProjectInterval.HOUR else MINUTE_INTERVAL_FORMAT
        when_str = f"_{when.strftime(time_format)}"
        location, today = self.get_day_path(skip_ensure=skip_ensure, when=when)
        if location is None:
            return None

        s = f"_{name}" if name else ""
        d = f"_{self.device_id}" if self.device_id else ""
        prefix = f"{today}{d}{when_str}{s}"

        return IntervalSource(location, prefix, when.hour if interval == ProjectInterval.HOUR else when.minute)

    def get_session_path(self, name: str = "", session: int = -1, skip_ensure: bool = False,
                         when: Optional[datetime] = None) -> Optional[SessionSource]:
        (location, today) = self.get_day_path(True, when=when)

        s_idx = session if session >= 0 else self.session
        session_str = f"session{s_idx:03}"
        location = os.path.join(location, session_str)

        if not skip_ensure and self.ensure_exists:
            if not _safe_ensure_location(location):
                return None

        d = f"_{self.device_id}" if self.device_id else ""
        prefix = f"{today}{d}_{session_str}"
        s = f"_{name}" if name else ""
        prefix = f"{prefix}{s}"

        return SessionSource(location, prefix, s_idx)

    def get_source_path(
        self,
        name: str = "",
        interval: ProjectInterval = ProjectInterval.NONE,
        session: int = -1,
        skip_ensure: bool = False,
        when: Optional[datetime] = None,
    ) -> Optional[ProjectPath]:
        if interval is None or interval == ProjectInterval.NONE:
            path = self.get_session_path(name, session=session, skip_ensure=skip_ensure, when=when)
        else:
            path = self.get_interval_path(name, interval=interval, skip_ensure=skip_ensure, when=when)

        return None if path is None else ProjectPath(path.location, path.prefix,
                                                     os.path.join(path.location, path.prefix))

    def get_metadata_file(self, session: int = -1, when: Optional[datetime] = None) -> str:
        when = (self.when if self.when is not None else _get_datetime_now()) if when is None else  when
        timestamp = when.strftime(TIME_FORMAT)

        if session is None:
            location, prefix = self.get_day_path(when=when)
            d = f"_{self.device_id}" if self.device_id else ""
            return os.path.join(location, f"{prefix}{d}_{timestamp}_metadata")
        else:
            source = self.get_session_path("metadata", session=session)
            return os.path.join(source.location, f"{source.prefix}")

    def get_monitor_file(self, name: str = "monitor", ext: str = "csv",
                         interval: ProjectInterval = ProjectInterval.HOUR,
                         when: Optional[datetime] = None) -> Optional[IntervalFileInfo]:
        path = self.get_interval_path(name, interval, when=when)
        return None if path is None else IntervalFileInfo(path.location,
                                                          os.path.join(path.location, f"{path.prefix}.{ext}"),
                                                          path.interval)

    def get_audio_spectrum_file(
        self,
        name: str = "spectrum",
        ext: str = "csv",
        interval: ProjectInterval = ProjectInterval.HOUR,
        when: Optional[datetime] = None
    ) -> Optional[IntervalFileInfo]:
        path = self.get_interval_path(name, interval, when=when)
        return None if path is None else IntervalFileInfo(path.location,
                                                          os.path.join(path.location, f"{path.prefix}.{ext}"),
                                                          path.interval)

    def get_webcam_presence_file(
        self,
        name: str = "cage",
        ext: str = "csv",
        interval: ProjectInterval = ProjectInterval.HOUR,
    ) -> Optional[IntervalFileInfo]:
        path = self.get_interval_path(name, interval)
        return None if path is None else IntervalFileInfo(path.location,
                                                          os.path.join(path.location, f"{path.prefix}.{ext}"),
                                                          path.interval)

    def get_video_path(
        self,
        name: str = "",
        interval: ProjectInterval = ProjectInterval.NONE,
        session: int = -1,
        allow_overwrite: bool = False,
    ) -> Union[Tuple[str, str, str], Tuple[None, None, None]]:
        """Get the 3-tuple of video paths for given arguments"""
        path = self.get_source_path(name, interval=interval, session=session)
        if path is None:
            return None, None, None

        file_name = f"{path.full_path}.{video_write_ext}"
        index = 0

        if not allow_overwrite:
            while os.path.exists(file_name):
                index += 1
                file_name = f"{path.full_path}_{index}.{video_write_ext}"

        modifier = "" if index == 0 else "_" + str(index)

        ts_file = f"{path.full_path}_timestamps{modifier}.txt"
        frames_processed_indices_file = f"{path.full_path}_processed_frames.txt"

        return file_name, ts_file, frames_processed_indices_file

    def get_image_capture_path(self,
        name: str = "",
        interval: ProjectInterval = ProjectInterval.NONE,
        session: int = -1,
        when: Optional[datetime] = None,
    ) -> Union[Tuple[str, str], Tuple[None, None]]:
        """Get the 2-tuple of image paths for given arguments"""
        base = self.get_source_path(name, interval=interval, session=session, skip_ensure=True, when=when)

        image_location = os.path.join(base.location, f"{base.prefix}{IMAGE_CAPTURE_SUFFIX}")

        if self.ensure_exists:
            if not _safe_ensure_location(image_location):
                return None, None

        image_file_format_str = base.prefix + "_{when}" + ".png"

        return image_location, image_file_format_str

    def get_intersession_pose_path(
        self,
        name: str = "",
        session: int = -1,
        allow_overwrite: bool = False,
        *,
        suffix: str = "",
        when: Optional[datetime] = None,
    ) -> str:
        source = self.get_source_path(name, session=session, when=when)
        file_name = os.path.join(source.location, f"{source.prefix}_raw2D{suffix}.h5")
        index = 0
        if not allow_overwrite:
            while os.path.exists(file_name):
                index += 1
                file_name = os.path.join(source.location, f"{source.prefix}_{index}.h5")
        return file_name

    def calculate_next_session_index(self):
        """Calculate the next session index & date and store it locally"""
        when = _get_datetime_now()
        location, _ = self.get_day_path(when=when)
        logger.debug(f"calculating next session index in {location}")
        path = Path(location)
        if not path.exists() or not path.is_dir():
            with self:
                self.session = 1
                self.when = when
            return

        session_dirs = [x.name[-3:] for x in path.iterdir() if x.is_dir() and "session" in x.name]

        def int_map_fcn(value: str):
            try:
                return int(value)
            except (ValueError, TypeError):
                return None

        session_vals = [int(x) for x in session_dirs if int_map_fcn(x) is not None]

        if len(session_vals) == 0:
            logger.debug(f"no existing sessions found")
            with self:
                self.session = 1
                self.when = when
        else:
            logger.debug(f"found {len(session_vals)} existing session directories")
            session_vals.sort(reverse=True)
            logger.debug(f"last session index for day: {session_vals[0]}")
            with self:
                self.session = session_vals[0] + 1
                self.when = when

    def to_local_value(self) -> Self:
        """Detach, if it was, from the possible shared memory values used for `when` & `session`.
        This ensures that the "detached" instance won't have its `when` and `session` values updated
         in the background by any other process attached to the shared values.
        """
        with self:
            sess_idx, when = self.session, self.when
        return self.__class__(
            root=self.root,
            device_id=self.device_id,
            ensure_exists=self.ensure_exists,
            camera_1=self.camera_1,
            camera_2=self.camera_2,
            # see ProjectInfo.__init__ :
            session=sess_idx,
            when=when,
        )
