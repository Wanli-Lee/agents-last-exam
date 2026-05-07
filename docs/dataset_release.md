# Dataset Release Boundary

The canonical public dataset layer lives on Hugging Face:

```text
agents-last-exam/agents-last-exam
```

This GitHub repository contains the harness, task examples, and release
documentation.

## Public By Default

- task instructions
- agent-visible input-material manifests
- public input files when available
- software/environment metadata
- public trajectory metadata, if selected for release

## Not Public By Default

- hidden gold outputs
- evaluator gold files
- private reference artifacts
- licensed software images
- private asset locations
- credentials

## Canonical Public Release

The Hugging Face dataset currently exposes the public 150-task release through:

- `public_150_tasks.jsonl`
- `public_150_tasks.csv`
- `public_150_input_files.csv`
- `public_150_summary.json`
- `public_150_tasks.zip`
- `neurips2026_croissant.json`

The public release is designed for task inspection, dataset-material review,
and agent-run preparation. It is not a hidden-answer release: official scoring
requires the private evaluator or a later maintainer-approved public evaluation
release.

## Local Smoke-Test Subset

`examples/hf_trial_subset` contains five task records across:

- enterprise workflow
- robotics
- computational chemistry
- VFX
- audio production

Only the Odoo task includes actual local input files in the trial package. The
other records are manifest-only examples: they list the expected agent-visible
materials, but the actual assets are not included in this trial package.
