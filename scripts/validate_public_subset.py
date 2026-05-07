"""Validate public dataset files and screen a release tree for leakage strings."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable


REQUIRED_FIELDS = {
    "task_id",
    "category",
    "title",
    "instruction",
    "input_materials",
    "software_summary",
    "input_completeness_note",
}

LEAK_PATTERNS = [
    r"/Users/[^\s]+",
    r"\\Users\\[^\\\s]+\\",
    r"\b[A-Z]:\\",
    r"/(?:media|mnt|home)/[^\s]+",
    r"(?:gs|s3)://[^\s]+",
    r"service[-_ ]?account",
    r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
    r"paper submission artifacts",
    r"should be reviewed before pushing",
    r"canonical release branch",
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
]

VALIDATOR_PATTERN_LITERAL_ALLOWLIST = {
    r"/Users/[^\s]+",
    r"\\Users\\[^\\\s]+\\",
    r"\b[A-Z]:\\",
    r"/(?:media|mnt|home)/[^\s]+",
    r"(?:gs|s3)://[^\s]+",
    r"service[-_ ]?account",
    r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
    r"paper submission artifacts",
    r"should be reviewed before pushing",
    r"canonical release branch",
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
}

TEXT_SUFFIXES = {
    "",
    ".cff",
    ".csv",
    ".gitignore",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
}

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}


def text_for_release_scan(file_path: Path, root: Path) -> str:
    text = file_path.read_text(encoding="utf-8", errors="replace")
    if root.is_dir() and file_path.relative_to(root) == Path("scripts/validate_public_subset.py"):
        for allowed_literal in VALIDATOR_PATTERN_LITERAL_ALLOWLIST:
            text = text.replace(allowed_literal, "")
    return text


def iter_text_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    for candidate in path.rglob("*"):
        if not candidate.is_file():
            continue
        if any(part in SKIP_DIRS for part in candidate.parts):
            continue
        if candidate.suffix in TEXT_SUFFIXES:
            yield candidate


def validate_jsonl(jsonl_path: Path, failures: list[str]) -> None:
    for lineno, line in enumerate(jsonl_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            failures.append(f"{jsonl_path}:{lineno}: invalid JSONL row: {exc}")
            continue
        missing = REQUIRED_FIELDS - row.keys()
        if missing:
            failures.append(f"{jsonl_path}:{lineno}: missing {sorted(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="A release directory or a JSONL file to validate.")
    args = parser.parse_args()

    failures = []
    scanned = 0
    jsonl_files = []
    for file_path in iter_text_files(args.path):
        scanned += 1
        rel = file_path.relative_to(args.path) if args.path.is_dir() else file_path
        text = text_for_release_scan(file_path, args.path)
        for pattern in LEAK_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                failures.append(f"{rel}: matched leak pattern {pattern!r}")
        if file_path.suffix == ".jsonl":
            jsonl_files.append(file_path)

    for jsonl_path in jsonl_files:
        validate_jsonl(jsonl_path, failures)

    if failures:
        for failure in failures:
            print(failure)
        raise SystemExit(1)
    print(f"validated {args.path} ({scanned} text files, {len(jsonl_files)} JSONL files)")


if __name__ == "__main__":
    main()
