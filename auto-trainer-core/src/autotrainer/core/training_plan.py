from pathlib import Path

from autotrainer.core.logging import get_verbose_logger

from autotrainer.training import TrainingPlan


logger = get_verbose_logger(__name__)


def load_training_plans(dir_path: Path):
    files = list(dir_path.glob("*.json"))
    plans = {}
    logger.verbose("Loading training plans: %s", files)
    for path in files:
        plans[path] = TrainingPlan.from_json_file(path)
    plans_seen = {}
    for path, plan in plans.items():
        prev = plans_seen.setdefault(plan.plan_id, path)
        if prev != path:
            raise RuntimeError(f"Training Protocols: same plan_id: {prev} vs {path}")
    return list(plans.values())
