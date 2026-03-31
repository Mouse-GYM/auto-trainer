import dataclasses


@dataclasses.dataclass
class SystemMaintenanceConfig:

    use_max_pellet_loaded: bool = True
    auto_resume_on_max_pellets_loaded: bool = True
    max_pellets_loaded_count: int = 500

    use_max_consecutive_failed_load: bool = True
    auto_resume_on_max_consecutive_failed_load: bool = True
    max_consecutive_failed_loaded: int = 10

    use_free_disk_space: bool = True
    auto_resume_on_free_disk_space: bool = True
    free_disk_space_min_limit_mb: int = 500
