"""Download or snapshot a public Hugging Face dataset for Agents' Last Exam."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-id",
        default="agents-last-exam/agents-last-exam",
        help="Hugging Face dataset repo id.",
    )
    parser.add_argument("--revision", default=None)
    parser.add_argument("--local-dir", default="data/hf")
    args = parser.parse_args()

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("Install with `python -m pip install -e .[hf]` first.") from exc

    local_dir = Path(args.local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_download(
        repo_id=args.repo_id,
        repo_type="dataset",
        revision=args.revision,
        local_dir=str(local_dir),
    )
    print(path)


if __name__ == "__main__":
    main()
