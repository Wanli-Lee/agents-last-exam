# Agents' Last Exam

[🤗 Dataset](https://huggingface.co/datasets/agents-last-exam/agents-last-exam) | [Task Schema](docs/task_schema.md) | [Agent Adapter](docs/agent_adapter.md) | [Dataset Release Notes](docs/dataset_release.md)

Agents' Last Exam is a benchmark effort for evaluating computer-use agents on
real-world professional workflows. This repository is an alpha public skeleton:
it documents the task interface, shows the intended dataset-material format,
and includes minimal code paths for running Cua-compatible tasks.

This repository is not the full runnable benchmark release. Full benchmark
assets, hidden evaluations, licensed software images, and private reference
artifacts are not included.

## Updates

- 2026-05-07: Added the canonical Hugging Face dataset entry point:
  `agents-last-exam/agents-last-exam`.
- 2026-05-06: Initial public skeleton branch with task harness examples,
  release-boundary docs, and a small metadata example.

## Dataset

The canonical public dataset is hosted on Hugging Face:

```text
agents-last-exam/agents-last-exam
```

The Hugging Face release is the public 150-task release. Its canonical files
are:

- `public_150_tasks.jsonl`: primary task manifest.
- `public_150_tasks.csv`: CSV view of the same task rows.
- `public_150_input_files.csv`: manifest of public input/software files
  included in the release package.
- `public_150_summary.json`: package-level counts and provenance metadata.
- `public_150_tasks.zip`: archive of the public `tasks/` directory.
- `neurips2026_croissant.json`: Croissant metadata.

The dataset includes public task instructions, input-material metadata,
available public input/software files, and per-task software/environment
metadata.

It excludes hidden reference outputs, private scoring fixtures, credentials, VM
images, evaluator gold files, and private reference artifacts.

Load the task table with `datasets`:

```python
from datasets import load_dataset

dataset = load_dataset(
    "agents-last-exam/agents-last-exam",
    data_files="public_150_tasks.jsonl",
    split="train",
)
print(dataset[0]["task_id"], dataset[0]["instruction"][:200])
```

Download the full public dataset package:

```bash
python scripts/download_dataset.py --local-dir data/agents-last-exam
```

Inspect individual public task cards after download:

```bash
ls data/agents-last-exam/tasks
cat data/agents-last-exam/tasks/001_basic__game__mota_exploration/instruction.md
cat data/agents-last-exam/tasks/001_basic__game__mota_exploration/input_materials.json
cat data/agents-last-exam/tasks/001_basic__game__mota_exploration/software.json
```

A small local example remains at `examples/hf_trial_subset` for repository
smoke tests and dataset-shape development.

See `docs/dataset_release.md` for the public/private release boundary.

## Installation

Use Python 3.12 or 3.13:

```bash
git clone https://github.com/cua-verse/agenthle-base
cd agenthle-base

PYTHON_BIN=python3.12  # or python3.13
$PYTHON_BIN -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

To run desktop tasks, also install the Cua extras:

```bash
python -m pip install -e ".[cua]"
```

## Quick Start

Inspect the local dataset example and public task metadata:

```bash
python quickstart.py
```

Download the Hugging Face dataset package:

```bash
python scripts/download_dataset.py --local-dir data/agents-last-exam
```

Run the minimal task with a Cua-compatible desktop endpoint:

```bash
export CUA_ENV_API_URL="http://YOUR_REMOTE_DESKTOP_ENDPOINT:5000"
export OPENAI_API_KEY="YOUR_OPENAI_COMPATIBLE_KEY"

python run.py --task tasks/helloworld --model openai/computer-use-preview
```

The lower-level shell entry point is also available:

```bash
bash scripts/run_task.sh tasks/helloworld openai/computer-use-preview
```

## Experiments

The public skeleton contains:

- `tasks/helloworld`: a minimal runnable Cua task that checks for a saved file.
- `tasks/game/mota_24_easy`: a code-only GUI task pattern. It requires a public
  SWF asset supplied by the user before it can be run.
- `examples/hf_trial_subset`: a 5-task metadata example for dataset upload
  shape testing.
- `data/agents-last-exam`: default local destination for the Hugging Face
  dataset package when downloaded with `scripts/download_dataset.py`.

Validate the public tree before publishing or uploading a dataset package:

```bash
python scripts/validate_public_subset.py .
```

## Evaluation

### Local Evaluation

Agents should read task instructions, interact with the desktop/session, and
write final deliverables into the task's `output/` directory. See
`docs/agent_adapter.md` for the expected integration contract.

Evaluate an existing run:

```bash
bash scripts/evaluate_task.sh tasks/helloworld
```

Summarize local evaluation JSON files:

```bash
python show_result.py --result-dir ./trycua/cua-bench
```

### Public Evaluation

The Hugging Face release is the public task-material layer, not a hidden-answer
release. A public evaluation run should use the task row as the agent-visible
contract:

1. Load `public_150_tasks.jsonl`.
2. For a selected task, read its `instruction`, `input_materials`, and
   `software_summary`.
3. Prepare the listed public input/software files from the downloaded `tasks/`
   directory when they are present.
4. Run the agent in an environment that provides the required software.
5. Require the agent to write deliverables to the task's `output/` directory or
   to the output path specified by the task instruction.
6. Evaluate submissions with the private benchmark evaluator or a maintainer
   verified evaluation harness.

The public dataset intentionally does not include hidden reference outputs or
private scoring fixtures. This means external users can inspect task design and
run agents against the public task materials, while official scoring still
requires the private evaluator or a later maintainer-approved public evaluation
release.

Minimal task-loop sketch:

```python
from datasets import load_dataset

tasks = load_dataset(
    "agents-last-exam/agents-last-exam",
    data_files="public_150_tasks.jsonl",
    split="train",
)

for task in tasks:
    instruction = task["instruction"]
    materials = task["input_materials"]
    software = task["software_summary"]
    # 1. provision software/materials
    # 2. run your computer-use agent with `instruction`
    # 3. collect files written to the requested output location
    # 4. submit outputs to the official/private evaluator when available
```

## Repository Layout

```text
tasks/                         Cua-compatible task examples
utils/                         Public evaluation helpers
scripts/                       Runner, evaluator, dataset, and validation helpers
docs/                          Schema, dataset boundary, and agent integration docs
examples/hf_trial_subset/       Small public dataset-material example
quickstart.py                  Inspect the local dataset example
run.py                         Python wrapper around the task runner
show_result.py                 Summarize local evaluation outputs
```

## FAQ

### Is this the full 240-task benchmark?

No. This is a public skeleton for the harness and dataset-material format.

### Are hidden answers or evaluator gold files included?

No. Hidden gold outputs, evaluator gold files, and private reference artifacts
are intentionally excluded.

### Can I run every listed task from this repo alone?

No. Some rows in the example dataset are manifest-only: they show the expected
agent-visible materials, but the actual assets are not included in this trial
package.

## Citation

If you use this benchmark harness, please cite this repository.
