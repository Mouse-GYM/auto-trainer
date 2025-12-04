
from pathlib import Path
from typing import Dict

from autotrainer.core.logging import get_verbose_logger

from autotrainer.training import TrainingPlan


logger = get_verbose_logger(__name__)


def load_training_plan_from_path(path: Path):
    return TrainingPlan.from_json_file(path)


def load_training_plans(dir_path: Path) -> Dict[Path, TrainingPlan]:
    files = list(dir_path.glob("*.json"))
    plans: Dict[Path, TrainingPlan] = {}
    logger.verbose("Loading training plans: %s", files)
    for path in files:
        plans[path] = load_training_plan_from_path(path)
    phase_ids = {}
    for path, plan in plans.items():
        for phase in plan.phases:
            prev_path, prev_phase = phase_ids.setdefault(phase.phase_id, (path, phase))
            if path != prev_path:
                raise RuntimeError(f"Duplicated phase_id: {phase.phase_id} in path {path} vs {prev_path}")
            if id(prev_phase) != id(phase):
                raise RuntimeError(f"Duplicated phase_id: {phase.phase_id} in path {path}: {prev_phase} vs {phase}")
    return plans
