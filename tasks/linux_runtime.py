"""Shared Linux runtime helpers for Ubuntu-native tasks."""

from __future__ import annotations

from dataclasses import dataclass

from tasks.common_config import GeneralTaskConfig


@dataclass
class LinuxTaskConfig(GeneralTaskConfig):
    """Base config for Ubuntu-native tasks.

    Same data-root injection model as :class:`GeneralTaskConfig` (see its
    module docstring); only the path separator differs (POSIX ``/``).
    """

    DOMAIN_NAME: str = ""
    OS_TYPE: str = "linux"
    VARIANT_NAME: str = "base"

    @property
    def task_dir(self) -> str:
        return f"{self.data_root}/{self.DOMAIN_NAME}/{self.TASK_NAME}/{self.VARIANT_NAME}"

    @property
    def input_dir(self) -> str:
        return f"{self.task_dir}/input"

    @property
    def reference_dir(self) -> str:
        return f"{self.task_dir}/reference"

    @property
    def software_dir(self) -> str:
        return f"{self.task_dir}/software"

    @property
    def output_dir(self) -> str:
        return f"{self.task_dir}/{self.OUTPUT_SUBDIR}"
