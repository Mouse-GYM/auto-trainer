from __future__ import annotations

import ctypes
import logging
import multiprocessing
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from multiprocessing import Value
from pathlib import Path
from typing import Tuple, NamedTuple, Union, Optional

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
        logger.warning("Could not create dir %r: %s", location, err)
        return False
    return True


# Windows does not like .mp4 extension when opencv is technically saving to an mkv container.
video_write_ext = "mp4" if sys.platform.startswith("linux") else "mkv"


@dataclass
class ProjectInfo:
    session: Value = None
    root: str = ""
    device_id: str = ""
    when: datetime = None
    ensure_exists: bool = False
    camera_1: str = ""
    camera_2: str = ""

    def __post_init__(self):
        if self.session is None:
            ctx = get_mp_ctx()
            self.session = ctx.Value(ctypes.c_uint32, 1)

    def is_valid(self):
        return self.root is not None and len(self.root) > 0

    def get_day_path(self, skip_ensure: bool = False) -> Union[Tuple[str, str], Tuple[None, None]]:
        today = (self.when if self.when is not None else datetime.now()).strftime(DATE_FORMAT)

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

        when = self.when if self.when is not None else datetime.now()

        return when.hour if interval == ProjectInterval.HOUR else when.minute

    def get_interval_path(self, name: str = "", interval: ProjectInterval = ProjectInterval.HOUR,
                          skip_ensure: bool = False) -> IntervalSource | None:
        when = self.when if self.when is not None else datetime.now()

        time_format = HOUR_INTERVAL_FORMAT if interval == ProjectInterval.HOUR else MINUTE_INTERVAL_FORMAT
        when_str = f"_{when.strftime(time_format)}"

        location, today = self.get_day_path(skip_ensure=skip_ensure)

        if location is None:
            return None

        s = f"_{name}" if name else ""

        d = f"_{self.device_id}" if self.device_id else ""

        prefix = f"{today}{d}{when_str}{s}"

        return IntervalSource(location, prefix, when.hour if interval == ProjectInterval.HOUR else when.minute)

    def get_session_path(self, name: str = "", session: int = -1, skip_ensure: bool = False) -> SessionSource | None:
        (location, today) = self.get_day_path(True)

        s_idx = session if session >= 0 else self.session.value

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

    def get_source_path(self, name: str = "", interval: ProjectInterval = ProjectInterval.NONE, session: int = -1,
                        skip_ensure: bool = False) -> Optional[ProjectPath]:
        if interval is None or interval == ProjectInterval.NONE:
            path = self.get_session_path(name, session=session, skip_ensure=skip_ensure)
        else:
            path = self.get_interval_path(name, interval=interval, skip_ensure=skip_ensure)

        return None if path is None else ProjectPath(path.location, path.prefix,
                                                     os.path.join(path.location, path.prefix))

    def get_metadata_file(self, session: int = None) -> str:
        timestamp = (self.when if self.when is not None else datetime.now()).strftime(TIME_FORMAT)

        if session is None:
            location, prefix = self.get_day_path()

            d = f"_{self.device_id}" if self.device_id else ""

            return os.path.join(location, f"{prefix}{d}_{timestamp}_metadata")
        else:
            source = self.get_session_path("metadata", session=session)

            return os.path.join(source.location, f"{source.prefix}")

    def get_monitor_file(self, name: str = "monitor", ext: str = "csv",
                         interval: ProjectInterval = ProjectInterval.HOUR) -> IntervalFileInfo | None:
        path = self.get_interval_path(name, interval)

        return None if path is None else IntervalFileInfo(path.location,
                                                          os.path.join(path.location, f"{path.prefix}.{ext}"),
                                                          path.interval)

    def get_audio_spectrum_file(self, name: str = "spectrum", ext: str = "csv",
                         interval: ProjectInterval = ProjectInterval.HOUR) -> IntervalFileInfo | None:
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
    ) -> Union[Tuple[str, str], Tuple[None, None]]:
        """Get the 2-tuple of image paths for given arguments"""
        base = self.get_source_path(name, interval=interval, session=session, skip_ensure=True)

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
    ) -> str:
        source = self.get_source_path(name, session=session)
        file_name = os.path.join(source.location, f"{source.prefix}_raw2D{suffix}.h5")
        index = 0
        if not allow_overwrite:
            while os.path.exists(file_name):
                index += 1
                file_name = os.path.join(source.location, f"{source.prefix}_{index}.h5")
        return file_name

    def calculate_next_session_index(self) -> None:
        location, _ = self.get_day_path()

        logger.debug(f"calculating next session index in {location}")

        path = Path(location)

        if not path.exists() or not path.is_dir():
            self.session.value = 1
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
            self.session.value = 1
        else:
            logger.debug(f"found {len(session_vals)} existing session directories")

            session_vals.sort(reverse=True)

            logger.debug(f"last session index for day: {session_vals[0]}")

            self.session.value = session_vals[0] + 1
