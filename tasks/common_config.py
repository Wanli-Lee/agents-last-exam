"""Common public task configuration helpers."""

import os
from dataclasses import dataclass


@dataclass
class GeneralTaskConfig:
    """Base configuration shared by public demo tasks."""

    REMOTE_OUTPUT_DIR: str = os.environ.get("REMOTE_OUTPUT_DIR", "output")
    REMOTE_ROOT_DIR: str = os.environ.get("REMOTE_ROOT_DIR", "benchmark_workspace")
    TASK_CATEGORY: str = os.environ.get("TASK_CATEGORY", "tasks")
    OS_TYPE: str = os.environ.get("OS_TYPE", "windows")
    TASK_TAG: str = ""

    @property
    def task_description(self) -> str:
        """Agent-facing task instruction."""
        return ""

    @property
    def task_dir(self) -> str:
        return fr"{self.REMOTE_ROOT_DIR}\{self.TASK_CATEGORY}\{self.TASK_TAG}"

    @property
    def software_dir(self) -> str:
        return fr"{self.task_dir}\software"

    @property
    def remote_output_dir(self) -> str:
        return fr"{self.task_dir}\{self.REMOTE_OUTPUT_DIR}"

    def to_metadata(self) -> dict:
        return {
            "task_tag": self.TASK_TAG,
            "task_dir": self.task_dir,
            "software_dir": self.software_dir,
            "remote_output_dir": self.remote_output_dir,
            "os_type": self.OS_TYPE,
        }
