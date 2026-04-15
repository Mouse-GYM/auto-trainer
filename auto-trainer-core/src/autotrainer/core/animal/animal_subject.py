import dataclasses
import datetime
import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional, Dict, Any, List
from typing_extensions import Self

from autotrainer.core import Offset3DTuple, get_verbose_logger

logger = get_verbose_logger(__name__)


_date_format = "%Y%m%d"


def _load_old_format(data: Dict[str, Any]) -> "AnimalSubject":
    kw = {}
    if "name" in data:
        kw['name'] = data["name"]
    animal = AnimalSubject(**kw)
    if "pellet_x" in data and "pellet_y" in data and "pellet_z" in data:
        animal.pellet_x = data["pellet_x"]
        animal.pellet_y = data["pellet_y"]
        animal.pellet_z = data["pellet_z"]
    return animal


@dataclass
class AnimalTraining:
    """Animal Training configuration"""

    # NB: protocol == plan ; todo: could/should better be moved to auto-trainer-training repo

    current_protocol: Optional[str] = None
    protocols: List[Dict[str, Any]] = dataclasses.field(default_factory=list)

    def get_plan_progress(self, plan_id: str) -> Optional[Dict[str, Any]]:
        # {"plan_id": self.plan_id,
        #                 "progress_state": self.progress_state,
        #                 "current_phase_id": None if self.current_phase is None else self.current_phase.phase_id,
        #                 "progress": progress
        #                 }
        for prot in self.protocols:
            if prot.get('plan_id') == plan_id:
                return prot
        return None

    def set_plan_progress(self, plan_id: str, progress: Dict[str, Any]):
        for idx, prog in enumerate(self.protocols):
            if prog['plan_id'] == plan_id:
                self.protocols[idx] = progress
                return
        self.protocols.append(progress)


@dataclass
class AnimalPelletCounts:
    presented: int = 0   # == successfully sent/delivered to the animal
    reaches: int = 0
    success_reaches: int = 0
    consumed: int = 0


@dataclass
class _AnimalSubject:
    """A subject in an animal experiment."""

    version: int = 2

    name: str = ""
    id: str = None   # handled in post_init

    is_pellet_dcs: bool = False
    pellet_x: float = 0
    pellet_y: float = 0
    pellet_z: float = 0

    training: AnimalTraining = dataclasses.field(default_factory=AnimalTraining)

    pellet_counts_day_date: datetime.date = dataclasses.field(default_factory=datetime.date.today)
    pellet_counts_day: AnimalPelletCounts = dataclasses.field(default_factory=AnimalPelletCounts)
    pellet_counts_total: AnimalPelletCounts = dataclasses.field(default_factory=AnimalPelletCounts)

    target_y_limit: Optional[float] = None  # in DCS

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid.uuid4())
        if not self.name:
            self.name = f"Mouse-{self.id}"

    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.name!r}, id={self.id!r})"

    @classmethod
    def from_file(cls, file_path: Path) -> Optional[Self]:
        with file_path.open("r") as file:
            try:
                data = json.load(file)
                if not isinstance(data, dict):
                    if not data:
                        # assuming empty file
                        return cls()
                    raise ValueError(f"Invalid file format in {file_path} ; not a dict: %s", type(data))
                file_version = data.get("version", None)
                if file_version is None or file_version != AnimalSubject.version:
                    logger.notice("Loaded animal version %s vs current Animal version %s",
                                   file_version, AnimalSubject.version)
                if "id" not in data:
                    # old format
                    animal = _load_old_format(data)
                else:
                    reach = data.pop('reach')
                    pellet_dev = reach.pop('pelletDevice', None)
                    pellet_dcs = reach.pop('pelletDcs', None)
                    if pellet_dcs is None:
                        src = pellet_dev
                    else:
                        src = pellet_dcs
                    pellet_x, pellet_y, pellet_z = src['x'], src['y'], src['z']
                    training = data.pop('training')
                    pellet_counts_day_dct = data.pop("pelletCountsDay", {})
                    pellet_counts_total_dct = data.pop("pelletCountsTotal", {})
                    count_day_date_str: Optional[str] = data.pop('pelletCountsDayDate', None)
                    if count_day_date_str is None:
                        pellet_counts_day_date = datetime.date.today()
                    else:
                        pellet_counts_day_date = datetime.datetime.strptime(count_day_date_str, _date_format).date()
                    animal = cls(
                        id=data.pop('id'),
                        name=data.pop('name'),
                        is_pellet_dcs=pellet_dcs is not None,
                        target_y_limit=data.pop('targetYLimit', None),
                        pellet_x=pellet_x,
                        pellet_y=pellet_y,
                        pellet_z=pellet_z,
                        training=AnimalTraining(
                            current_protocol=training.pop('currentProtocol'),
                            protocols=training.pop('protocols'),
                        ),
                        pellet_counts_day_date=pellet_counts_day_date,
                        pellet_counts_day=AnimalPelletCounts(**pellet_counts_day_dct),
                        pellet_counts_total=AnimalPelletCounts(**pellet_counts_total_dct),
                    )
            except Exception as err:
                logger.error("Error loading animal subject from %s: %s", file_path, err)
                return None

        logger.debug("loaded animal id=%r name=%r pellet=%s is_dcs=%s current_protocol=%s",
                     animal.id, animal.name,
                     (animal.pellet_x, animal.pellet_y, animal.pellet_z), animal.is_pellet_dcs,
                     animal.training.current_protocol)

        return animal

    def to_file(self, file_path: Path):
        reach: Dict[str, Any] = {}
        key = "pelletDcs" if self.is_pellet_dcs else "pelletDevice"
        reach[key] = {
            'x': self.pellet_x,
            'y': self.pellet_y,
            'z': self.pellet_z,
        }
        data = {
            "version": self.version,
            "id": self.id,
            "name": self.name,
            "reach": reach,
            "training": {
                'currentProtocol': self.training.current_protocol,
                'protocols': self.training.protocols,
            },
            "targetYLimit": self.target_y_limit,
            "pelletCountsDayDate": self.pellet_counts_day_date.strftime(_date_format),
            "pelletCountsDay": dataclasses.asdict(self.pellet_counts_day),
            "pelletCountsTotal": dataclasses.asdict(self.pellet_counts_total),
        }
        xyz = Offset3DTuple(self.pellet_x, self.pellet_y, self.pellet_z)
        logger.debug("Saving %s to %s ; xyz=%s", self.name, file_path.as_posix(), xyz.humanize())
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", delete=False, dir=file_path.parent) as fh:
            json.dump(data, fh, indent=4)
        os.replace(fh.name, file_path)

    def check_today_date(self) -> bool:
        """Return True if changed"""
        today = datetime.date.today()
        prev = self.pellet_counts_day_date
        if prev != today:
            logger.debug("today (%s) != animal prev day date (%s), resetting day counts to 0",
                         today, prev)
            self.pellet_counts_day_date = today
            self.pellet_counts_day = AnimalPelletCounts()
            return True
        return False


@dataclass
class AnimalSubject(_AnimalSubject):

    def __init__(self, **kwargs):
        kwargs.pop('baseline_magnet_intensity', None)
        super().__init__(**kwargs)
