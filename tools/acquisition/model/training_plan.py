
from pathlib import Path
from typing import Dict

from autotrainer.core.logging import get_verbose_logger

from autotrainer.training import TrainingPlan


logger = get_verbose_logger(__name__)


def load_training_plans(dir_path: Path):
    files = list(dir_path.glob("*.json"))
    plans: Dict[Path, TrainingPlan] = {}
    logger.verbose("Loading training plans: %s", files)
    for path in files:
        plans[path] = TrainingPlan.from_json_file(path)
    plans_seen = {}
    for path, plan in plans.items():
        prev = plans_seen.setdefault(plan.plan_id, path)
        if prev != path:
            raise RuntimeError(f"Training Protocols: duplicated plan_id: {prev} vs {path}")
        phase_ids = {}
        for phase in plan.phases:
            prev = phase_ids.setdefault(phase.phase_id, phase)
            if prev != phase:
                raise RuntimeError(f"Duplicated phase_id: {phase.phase_id} in phase {phase.name} vs {prev.name}")
    return list(plans.values())
