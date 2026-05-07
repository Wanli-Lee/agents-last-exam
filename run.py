"""Python wrapper for running a Cua-compatible task."""

from __future__ import annotations

import argparse
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="tasks/helloworld")
    parser.add_argument("--model", default="openai/computer-use-preview")
    args = parser.parse_args()

    subprocess.run(["bash", "scripts/run_task.sh", args.task, args.model], check=True)


if __name__ == "__main__":
    main()
