# Contributing

Thank you for your interest in Agents' Last Exam.

This public repository is currently a lightweight benchmark harness and task
metadata skeleton. Contributions should keep the public/private boundary clear.

## Contribution Principles

- Keep public task instructions and input-material manifests separate from
  hidden gold outputs.
- Do not commit credentials, private bucket paths, VM IPs, or internal
  experiment configs.
- Do not add hidden references or evaluator gold files unless the project has
  explicitly decided to release them.
- Prefer small, reviewable task examples over large environment dumps.

## Local Checks

```bash
python scripts/validate_public_subset.py .
```

If Cua dependencies are installed and a remote desktop endpoint is available,
you can also run:

```bash
bash scripts/run_task.sh tasks/helloworld openai/computer-use-preview
```

## Adding a Task

A task should have:

- agent-facing instruction
- input-material manifest
- software/environment metadata
- expected output contract
- evaluator or public evaluation summary

See `docs/task_schema.md`.
