"""Inspect the local public dataset example."""

from __future__ import annotations

import json
from pathlib import Path


DATASET_PATH = Path("examples/hf_trial_subset/data/tasks.jsonl")


def main() -> None:
    if not DATASET_PATH.exists():
        raise SystemExit(f"Missing dataset example: {DATASET_PATH}")

    rows = [json.loads(line) for line in DATASET_PATH.read_text(encoding="utf-8").splitlines()]
    print(f"Loaded {len(rows)} task records from {DATASET_PATH}")
    for row in rows:
        status = row.get("local_input_status", "unknown")
        print(f"- {row['task_id']}: {row['title']} [{status}]")

    print("\nNext steps:")
    print("- Download the canonical dataset: python scripts/download_dataset.py --local-dir data/agents-last-exam")
    print("- Validate the release tree: python scripts/validate_public_subset.py .")
    print("- Read the task schema: docs/task_schema.md")
    print("- Run a Cua task when a desktop endpoint is available: python run.py --task tasks/helloworld")


if __name__ == "__main__":
    main()
