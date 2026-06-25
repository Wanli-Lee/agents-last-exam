# ALE Error Analysis — gpt-5.5 on ale-claw (100 failed cases)

Root-cause attribution of every failed ALE case (score < 0.99) from our `ale-claw + openai/gpt-5.5` runs, across both Linux (Docker) and Windows (GCP VM) sandboxes. Each case was deep-read by an independent agent (task requirement + produced output + full trajectory) and classified on a fixed schema.

- **100 failed cases** = 83 Linux + 17 Windows (deduplicated, latest run per task)
- Harness: ale-claw, GUI-as-Tool mode (computer / exec / read-write-edit / web / analyze_image / delegate_gui / memory)
- Grading: deliverable-based, deterministic where possible
- Raw data: `attributions.json` (full, with evidence) · `attributions.csv` (flat table)

---

## Headline: ~1/4 of "failures" are NOT the model's fault

| is_model_capability | count | meaning |
|---|---|---|
| `yes_capability` | 38 | genuine model capability gap |
| `mixed` | 33 | capability gap + env/other factors |
| `no_environment` | 13 | VM/sandbox/provisioning broke (e.g. docker absent, output download corrupted) |
| `no_eval_artifact` | 10 | model was basically right; harsh/exact-match grading scored it 0 |
| `no_harness` | 6 | harness file-transfer/restage corrupted a correct deliverable |

**71 are real model-capability issues (yes + mixed); 29 are environment / harness / grading artifacts.** When measuring the true capability gap, those 29 should be excluded — counting them inflates the failure rate by ~40%.

Example of a non-model failure: `business_finance/american_option_pricing_ls` originally scored **1.0**, but the harness's CUA output-download of `exercise_boundary_tier2.npy` failed, leaving an `.unreadable` placeholder; the eval-only re-run restaged from the corrupted copy and scored **0.0**. The model's solution was correct.

---

## Where the real capability gaps are (71 cases, yes+mixed)

| failure_locus | count |
|---|---|
| **domain_knowledge** | 26 |
| planning_longhorizon | 11 |
| coding_logic | 10 |
| output_format_spec | 8 |
| task_understanding | 4 |
| environment_infra | 4 |
| verification_selfcheck | 3 |
| gui_perception | 3 |
| gave_up_early | 2 |

**The #1 real gap is domain knowledge** (26): the model executes the tooling correctly but makes a wrong *expert judgment* — e.g. reversing a binary but submitting the decoy config, BPMN redesigns that violate role-separation rules, picking the wrong governance-suppression interpretation, computational-chemistry methodology errors. This is not a tool-use or GUI problem; it's expertise.

The #2/#3 gaps (planning over 100+ turns, coding logic) share a recurring pattern: **the model produces a schema-valid but hollow/incorrect deliverable and declares DONE without verifying** — populating only the latest year, hardcoding a constant, or self-checking with a loose regex instead of the grader's own library.

---

## Fix levers (all 100)

| fixable_by | count |
|---|---|
| better_model | 62 |
| env_fix | 18 |
| harness_fix | 11 |
| unfixable_eval_noise | 5 |
| prompt_fix | 4 |

**29 cases are fixable without touching the model** (env_fix 18 + harness_fix 11) — fixing the Docker provisioning and the CUA output-download/restage pipeline would directly recover them. That's the cheapest score gain available.

---

## Linux vs Windows

| | cases | real capability | env/harness/eval |
|---|---|---|---|
| Linux | 83 | 55 | 28 |
| Windows | 17 | 16 | 1 |

**Linux carries almost all the non-model failures (28 of 29).** The Linux Docker run hit far more provisioning/transfer issues (docker-in-docker absent, output-gather download errors, eval-only restage corruption). Windows failures are almost purely capability gaps. → The Linux *harness/env* is the lower-hanging fruit; Windows failures need a stronger model.

---

## Interleaving (GUI×CLI)

Only **14/100** failures happened at a GUI×CLI interleaving boundary. The vast majority of ALE failures are single-channel (pure CLI/domain/coding). This is consistent with ALE being CLI-dominant — GUI interleaving is rarely the failure point here (it is far more central in WeaveBench).

---

## So what to fix, in priority order

1. **Harness/env (29 cases, cheap)** — fix Docker provisioning + the CUA output-download/restage corruption. Several originally-correct solutions are being scored 0 purely by file-transfer breakage.
2. **Grading noise (10 `no_eval_artifact`)** — exact-match/casing-brittle graders zeroing near-correct deliverables (e.g. `## modification_1:` vs required `## Modification N`). Worth auditing graders.
3. **Domain knowledge (26, needs stronger model / domain SFT)** — the hard core; not fixable by harness.
4. **Verification discipline (recurring)** — the model declares DONE on hollow/unverified deliverables. A "verify with the grader's own method before submitting" behavior (RL-rewardable) would recover a cluster of coding/format failures.

See `attributions.json` for per-case evidence (turn citations, output-file states, grader outputs).
