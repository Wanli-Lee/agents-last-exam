"""Summarize local evaluation JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def score_from_json(path: Path) -> float | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data.get("score", data.get("final_score"))
    return float(value) if value is not None else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", default="./trycua/cua-bench")
    args = parser.parse_args()

    root = Path(args.result_dir)
    if not root.exists():
        raise SystemExit(f"Result directory does not exist: {root}")

    result_files = sorted(root.rglob("*evaluation*.json"))
    if not result_files:
        raise SystemExit(f"No evaluation JSON files found under {root}")

    scores = []
    for path in result_files:
        score = score_from_json(path)
        if score is None:
            print(f"{path}: no score field")
            continue
        scores.append(score)
        print(f"{path}: {score:.3f}")

    if scores:
        print(f"\nMean score: {sum(scores) / len(scores):.3f} over {len(scores)} files")


if __name__ == "__main__":
    main()
