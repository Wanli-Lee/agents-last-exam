# Task Schema

A public task record should describe the agent-visible contract without
revealing hidden gold outputs.

Required fields:

- `task_id`: stable category/task identifier.
- `category`: domain category.
- `title`: short readable name.
- `instruction`: agent-facing task instruction.
- `input_materials`: list of agent-visible input files or directories.
- `software_summary`: software or environment expected by the task.
- `input_completeness_note`: whether actual input files are included or only
  listed as a manifest.

Recommended fields:

- `instruction_source`
- `input_materials_summary`
- `hf_subset_input_files`
- `release_scope_note`

Do not include:

- hidden gold outputs
- evaluator gold files
- private VM paths or credentials
- unreleased reference artifacts
