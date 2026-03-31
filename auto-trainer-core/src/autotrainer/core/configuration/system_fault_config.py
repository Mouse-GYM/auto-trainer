import dataclasses


@dataclasses.dataclass
class SystemFaultConfig:

    use_free_disk_space: bool = True
    auto_resume_on_free_disk_space: bool = True
    free_disk_space_min_limit_mb: int = 500
