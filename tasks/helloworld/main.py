"""Minimal Cua task: save a milestone screenshot."""

import asyncio
import logging
from dataclasses import dataclass

import cua_bench as cb
from tasks.common_config import GeneralTaskConfig

logger = logging.getLogger(__name__)


@dataclass
class TaskConfig(GeneralTaskConfig):
    TASK_TAG: str = "HELLOWORLD"
    TASK_CATEGORY: str = "tasks"

    @property
    def milestone_path(self) -> str:
        return fr"{self.REMOTE_ROOT_DIR}\step1_opened.png"

    @property
    def task_description(self) -> str:
        return f"""
Goal: Save a milestone screenshot.

Use the available desktop tools to save a milestone screenshot at:

`{self.milestone_path}`

The task is successful if the milestone screenshot file exists.
"""

    def to_metadata(self) -> dict:
        metadata = super().to_metadata()
        metadata["milestone_path"] = self.milestone_path
        return metadata


config = TaskConfig()


@cb.tasks_config(split="train")
def load():
    return [
        cb.Task(
            description=config.task_description,
            metadata=config.to_metadata(),
            computer={"provider": "computer", "setup_config": {"os_type": config.OS_TYPE}},
        )
    ]


@cb.setup_task(split="train")
async def start(task_cfg, session: cb.DesktopSession):
    logger.info("Setting up helloworld task")
    await asyncio.sleep(1)


@cb.evaluate_task(split="train")
async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
    milestone_path = task_cfg.metadata["milestone_path"]
    try:
        return [1.0 if await session.exists(milestone_path) else 0.0]
    except Exception as exc:
        logger.error("Evaluation error: %s", exc)
        return [0.0]
