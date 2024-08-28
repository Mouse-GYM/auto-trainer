import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Tuple, NamedTuple

DATE_FORMAT = "%Y%m%d"

TIME_FORMAT = "%H%M%S"

HOUR_FORMAT = "%H"


class ProjectPath(NamedTuple):
    location: str
    prefix: str
    full_path: str


class HourlySource(NamedTuple):
    location: str
    prefix: str
    hour: int


class SessionSource(NamedTuple):
    location: str
    prefix: str
    session_index: int


@dataclass
class ProjectInfo:
    root: str = ""
    device_id: str = ""
    when: datetime = None
    current_session: int = 0

    def is_valid(self):
        return self.root is not None and len(self.root) > 0

    def get_path(self) -> str:
        if self.device_id:
            return os.path.join(self.root, self.device_id)

        return self.root

    def get_day_path(self) -> Tuple[str, str]:
        today = (self.when if self.when is not None else datetime.now()).strftime(DATE_FORMAT)

        return os.path.join(self.get_path(), today), today

    def get_hourly_source_path(self, source: str = "") -> HourlySource:
        when = self.when if self.when is not None else datetime.now()
        hour = when.strftime(HOUR_FORMAT)

        (location, today) = self.get_day_path()

        s = f"_{source}" if source else ""

        d = f"_{self.device_id}" if self.device_id else ""

        prefix = f"{today}{d}_h{hour}{s}"

        return HourlySource(location, prefix, when.hour)

    def get_session_source_path(self, source: str = "", session: int = None) -> SessionSource:
        (location, today) = self.get_day_path()

        s = self.current_session if session is None else session

        d = f"_{self.device_id}" if self.device_id else ""

        prefix = f"{today}{d}_session{s:03}"

        location = os.path.join(location, prefix)

        s = f"_{source}" if source else ""

        prefix = f"{prefix}{s}"

        return SessionSource(location, prefix, self.current_session)

    def get_source_path(self, source: str = "", is_hourly: bool = False) -> ProjectPath:
        if is_hourly:
            path = self.get_hourly_source_path(source)
        else:
            path = self.get_session_source_path(source)

        return ProjectPath(path.location, path.prefix, os.path.join(path.location, path.prefix))

    def get_metadata_file(self) -> str:
        timestamp = (self.when if self.when is not None else datetime.now()).strftime(TIME_FORMAT)

        location, prefix = self.get_day_path()

        d = f"_{self.device_id}" if self.device_id else ""

        return os.path.join(location, f"{prefix}{d}_{timestamp}_metadata.json")

    def get_video_timestamp_file(self, source: str = "", is_hourly: bool = False, modifier: str = "") -> str:
        path = self.get_source_path(source, is_hourly)

        return f"{path.full_path}_timestamps{modifier}.txt"

    def calculate_next_session_index(self):
        location, _ = self.get_day_path()

        path = Path(location)

        if not path.exists() or not path.is_dir():
            self.current_session = 1
            return

        session_dirs = [x.name[-3:] for x in path.iterdir() if x.is_dir() and "session" in x.name]

        def int_map_fcn(value: str):
            try:
                return int(value)
            except:
                return None

        session_vals = [int(x) for x in session_dirs if int_map_fcn(x) is not None]

        if len(session_vals) == 0:
            self.current_session = 1
            return

        session_vals.sort(reverse=True)

        self.current_session = session_vals[0] + 1
