import dataclasses


@dataclasses.dataclass
class SystemMaintenanceConfig:

    use_max_pellet_loaded: bool = True
    auto_resume_on_max_pellets_loaded: bool = True
    max_pellets_loaded_count: int = 500
