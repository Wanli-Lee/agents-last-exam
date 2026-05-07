"""Magic Tower code-only GUI task pattern with file-existence evaluation."""

import asyncio
import logging
from dataclasses import dataclass

import cua_bench as cb
from tasks.common_config import GeneralTaskConfig

logger = logging.getLogger(__name__)


@dataclass
class TaskConfig(GeneralTaskConfig):
    TASK_CATEGORY: str = "game"
    TASK_TAG: str = "GAME_MOTA_24_EZ"
    GAME_TAG: str = "mota-24"

    @property
    def game_url(self) -> str:
        return fr"{self.task_dir}\input\{self.GAME_TAG}.swf"

    @property
    def task_description(self) -> str:
        return f"""
Goal: Launch Magic Tower and navigate to the 3rd floor.

This code-only example expects a public SWF asset at `{self.game_url}` if you
choose to run it.

1. Open the game at `{self.game_url}`.
2. Wait for the game to load and enter the game.
3. Navigate to the 3rd floor.
4. For each floor reached, save a milestone screenshot at:
   `{self.remote_output_dir}\\$FLOOR_NUMBER$.png`

The public evaluator only checks whether the three milestone screenshots exist.
"""

    def to_metadata(self) -> dict:
        metadata = super().to_metadata()
        metadata.update({"game_tag": self.GAME_TAG, "game_url": self.game_url})
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
    game_url = task_cfg.metadata["game_url"]
    remote_output_path = task_cfg.metadata["remote_output_dir"]
    try:
        await session.run_file(game_url)
        await session.remove_file(remote_output_path)
        await session.makedirs(remote_output_path)
    except Exception as exc:
        logger.warning("Failed to launch game during setup: %s", exc)
    await asyncio.sleep(3)


@cb.evaluate_task(split="train")
async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
    output_dir = task_cfg.metadata["remote_output_dir"]
    expected = [fr"{output_dir}\{floor}.png" for floor in ("1", "2", "3")]
    try:
        found = [await session.exists(path) for path in expected]
        return [sum(found) / len(expected)]
    except Exception as exc:
        logger.error("Evaluation error: %s", exc)
        return [0.0]
