# ALE Case Review (caseview)

A static, single-page web viewer for reviewing gpt-5.5 runs on the ALE benchmark
(arXiv 2606.05405). For each task it shows a Chinese deep-dive analysis, the full
tool-call trajectory, the agent's deliverables (with inline content), and the
original prompt / scoring rubric in a bilingual (中文 / English) view.

## Files

```
caseview/
├── index.html          # task grid: stats, domain/tier/verdict filters, search
├── case.html           # per-case full page (?id=<task_id>)
└── scripts/            # data-generation scripts (run from the parent dir)
    ├── extract_trajectories.py   # condense trajectory.json -> data/trajectories/<id>.json
    ├── extract_artifacts.py      # extract output deliverables -> data/artifacts/<id>.json
    ├── translate_materials.py    # (LiteLLM variant) translate prompt + rubric to CN
    └── merge_translations.py     # merge translations into cases_full.json
```

Generated data (NOT committed — see `.gitignore`) lives in `caseview/data/`:

```
data/
├── cases_full.json            # 105 cases: base fields + analysis + CN translations
├── trajectories/<id>.json     # condensed per-step tool-call trace (lazy-loaded)
└── artifacts/<id>.json        # per-case deliverable contents (lazy-loaded)
```

## How the viewer works

- Pure static HTML/CSS/JS, no build step. `index.html` fetches `data/cases_full.json`;
  `case.html` additionally lazy-loads `data/trajectories/<id>.json` and
  `data/artifacts/<id>.json` only for the case being viewed.
- Serve the `caseview/` directory over HTTP and open `index.html`:

  ```bash
  cd caseview && python3 -m http.server 8123
  # then open http://<host>:8123/index.html
  ```

## Regenerating the data

The scripts read run logs from `repo/.logs/...` and write into `caseview/data/`.
They are written to run from the directory that contains both `caseview/` and the
run-log tree (i.e. the project root used during the runs). Paths inside the scripts
are relative (`caseview/data/...`, `repo/.logs/...`); adjust if your layout differs.

```bash
# 1. condensed trajectories (reads each run's trajectory.json)
python3 caseview/scripts/extract_trajectories.py

# 2. deliverable contents (reads each run's output/ dir; inlines readable text,
#    truncates >200KB, flags binary/.unreadable)
python3 caseview/scripts/extract_artifacts.py

# 3. translations: a workflow / LiteLLM step produces a translations payload,
#    then merge it into cases_full.json
python3 caseview/scripts/merge_translations.py <translations.json>
```

### Notes on the data model

- `score` is left as-is from the run; rejudge runs were cross-checked and did not
  change scores in a positive direction, so the original scores are kept.
- `exec_duration_s` / `queue_wait_s` are derived from `events.jsonl`
  (`agent_run_started` → `agent_finished` for net execution; provision wait is the
  queue time). The raw `run_duration_s` includes long provisioning queue waits and
  is therefore NOT used as the displayed runtime.
- Deliverables come from each task's declared `output_files`. Large/binary outputs
  are archived as `.unreadable` placeholders upstream and shown as "不可预览".
