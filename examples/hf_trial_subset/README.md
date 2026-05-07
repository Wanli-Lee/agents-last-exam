---
configs:
- config_name: tasks
  data_files:
  - split: trial
    path: data/tasks.jsonl
---

# Agents' Last Exam Trial Task Subset (5 Tasks)

This subset uses five representative benchmark tasks across enterprise workflow, robotics, computational chemistry, VFX, and audio production.

It includes:

- agent-facing task instructions
- agent-visible input-material manifests
- software/environment metadata
- available local input files when present

It excludes hidden gold outputs, evaluator gold files, and full benchmark solution artifacts.

## Files

- `data/tasks.jsonl`: one task record per row, including full instructions.
- `data/tasks.csv`: compact review table.
- `data/input_files.csv`: file-level manifest for included local input files.
- `input_materials/`: copied local input files where available.
- `summary.json`: subset counts.

## Input Availability

Only the Odoo task has actual local input files in this package. The other four tasks are manifest-only examples: they describe the expected agent-visible inputs, but the actual assets are not included here. This is sufficient to test the Hugging Face dataset shape before preparing a larger public or gated data release.
