# ALE vs simprun — detailed change log

Reference: simprun lives at `agenthle/scripts/web_console/lib/simprun/`.
This doc compares ALE (`agents-last-exam/`) as the next-gen replacement.

Scope: architectural choices, module reorganization, contract changes
between deployers / providers / lifecycle, and a per-detail accounting
of small parameters / timeouts / behaviours.

---

## 0. TL;DR

| Dimension | simprun | ALE |
|---|---|---|
| Lifecycle phases (named) | 4 (`provision` / `runtime_stage` / `task_setup` / `agent_run` / `evaluate` / `cleanup`) | 7 (`env_start` / `stage_inputs` / `task_setup` / `agent_run` / `stage_reference` / `evaluation` / `cleanup`) |
| VM provisioning | Multi-zone + multi-`CapacityProfile` fallback | Multi-zone fallback (single machine_type per provider) |
| Agent deployer interface | `Deployer.ensure_ready()` + `run_agent(prompt, timeout, raw_output_dir) -> dict` (sync, blocking) | `BaseAgentDeployer.install()` + `launch(prompt) -> AgentRunResult` (async) + `parse_artifacts()` classmethod |
| **Runtime abstraction** | None — deployer = "run claude CLI in VM" hard-baked | `vm` / `local` / `docker` substrate; deployer code identical across substrates |
| **Env / Provider abstraction** | None — `RemoteVMConfig` is a struct, VM lifecycle scattered across `runner.py` / `vm.py` / `data.py` | `Provider` ABC (acquire / release / open_session) + `AgenthleEnv` (OpenEnv-style reset/step/close) |
| Data staging (input/eval/reference/upload) | `data.py` free fns called from `runner._phase1_start` + `_phase3_evaluate` | `ale/io/data_staging.py` (async port) called from `AgenthleEnv.reset_async` + `step_async(Submit)` + `close_async` |
| Incremental log pull | `RangeStates` + `download_file_range` in `sync_helpers.py` + `remote.py`, called every 180s in deployer's poll loop | `ale/io/incremental_pull.py` (async port), runs as background `asyncio.Task` for 15s ticks during `agent_run` |
| Artifact mirror (output / origin_log) | `download_file` + custom path conventions, no GCS bridge | `ArtifactMirror` with GCS-bridge primary + cua-direct fallback, size-cap + retry |
| Concurrency model | Two sems: `Semaphore(max_in_flight)` (engine) + `ThreadPoolExecutor(max_workers)` (batch) | Two sems: `provision_concurrency` + `run_concurrency` (default eq) |
| API key flow | yaml ``api_keys: {OPENROUTER_API_KEY: ${env:...}}`` → config dataclass | Read directly from `os.environ` at runtime; framework propagates to docker (--env-file) / vm (spec.host_env) substrates |
| Resume | `--skip-completed` by output dir glob | Same; triggered by matching `ExperimentSpec.name` |
| Per-run state DB | Postgres via `state.py` | None — `run.json` + `events.jsonl` on disk |
| Error categorization | `events.py:classify_error` (INFRASTRUCTURE / STAGING / AGENT / EVALUATION) | `_classify_error` (rate_limited / vm_quota_exhausted / auth_failed / gcs_missing / transport_error / rpc_timeout); phase tag is separate |
| Force-cancel mechanism | `force_timeout.py` writes signal file to VM; deployer polls | None (deferred) |
| Web-console / external API | Yes (state.py / events.py drive web UI) | None — operator-facing only |

---

## 1. Architectural shifts

### 1.1 What got abstracted (NEW in ALE)

**Provider ABC** (`ale/core/provider.py`):
```python
class Provider(abc.ABC):
    async def acquire(self, spec: EnvSpec) -> VMHandle: ...
    async def release(self, vm: VMHandle, *, mode: ReleaseMode = "delete") -> None: ...
    def open_session(self, vm: VMHandle) -> cb.DesktopSession: ...
    async def heartbeat(self, vm: VMHandle) -> None: ...        # default no-op
    async def cancel_external(self, vm: VMHandle) -> None: ...   # default no-op
```
Concrete: `GCSDirectProvider` (simprun-equivalent), `StaticProvider` (point at
existing VM for dev/repro). Was previously scattered across simprun's
`runner.py` (`_phase0_provision`, `_phase4_cleanup`) + `vm.py` (gcloud) +
`task_env.py` (session ctor). Now one boundary per concept.

**Env** (`ale/core/env.py:AgenthleEnv`):
OpenEnv-style `Environment` subclass. Single `reset_async()` → `step_async(action)` →
`close_async()` contract. Bound to one `(task_path, variant)` at construction.
Replaces simprun's `TaskEnv` (which had no standard interface).

**Runtime abstraction** (`ale/runtime/`):
The biggest NEW concept. simprun deployers all assume "agent runs in the
VM as a CLI subprocess". ALE separates *where* the deployer runs:
- `vm` runtime — deployer code itself runs INSIDE the eval VM (via
  `cua.python_exec`). Used by claude_code.
- `local` runtime — deployer runs in host Python process; drives VM via
  cua RPC. Used by ale_claw (the OpenClaw harness imports as in-process
  library).
- `docker` runtime — deployer runs in a host docker container; drives VM
  via cua RPC. Same code as `local`, just sandboxed.

The deployer's `install()` / `launch()` use stdlib (`subprocess`, `pathlib`,
`json`) — they don't know or care where they're executing. The framework's
`Executor` (per runtime) places them. This makes adding `codex` or
`openhands` deployers trivial; in simprun adding a 13th deployer meant a
13th copy of "ssh + setsid + poll" boilerplate in `deployers/`.

**Trajectory + ATIF v1.0** (`ale/agents/trajectory.py`):
Standardized cross-agent log format (Steps with source / message / tool_calls
/ observations / metrics). simprun emitted whatever shape each deployer's
`run_agent` returned + a free-form `interaction_log` blob.

### 1.2 What got merged / dropped

- **Postgres state (state.py)** — dropped. ALE writes `run.json` per run dir;
  batch progress is `glob run.json` at the file system level. No web console
  → no DB.
- **External runner (`external/`) vs native runner duality** — collapsed.
  ALE has one runner (`ale/runner/runner.py`); provider abstraction handles
  the "leased VM" vs "owned VM" distinction.
- **`deployer_base.py` + 12 deployers** — simprun has each deployer carrying
  copy-pasted scp / setsid / pid-poll / log-sync logic. ALE moves all of
  that into the framework (Executor + IncrementalPuller + ArtifactMirror);
  per-deployer code shrinks to "install prereqs + spawn process + parse
  on-disk logs".
- **`web_console/` integration points** (events.py / monitor.py going to web
  UI) — dropped. `events.jsonl` is plain JSON on disk; whoever wants a
  dashboard parses it themselves.

### 1.3 Module mapping (file → file)

| simprun | ALE | Notes |
|---|---|---|
| `runner.py` (1400 LOC) | `ale/runner/lifecycle.py` (500 LOC) + `ale/core/env.py` (300 LOC) + `ale/runtime/*_executor.py` | Split: framework-vs-deployer-vs-substrate concerns separated |
| `batch.py` | `ale/runner/runner.py` + `ale/runner/resume.py` + `ale/cli.py` | Same: list units, sem, gather |
| `engine.py` (state machine + Postgres) | `ale/runner/runner.py` + `ale/io/run_writer.py` | DB → flat files |
| `vm.py` | `ale/providers/gcs_direct.py` | Capacity profile abstraction dropped; multi-zone kept |
| `data.py` | `ale/io/data_staging.py` | Async port; functionally equivalent |
| `remote.py` (CUA HTTP + sync transport) | (gone — uses cua-bench `RemoteDesktopSession`) | cua-bench's own client now |
| `sync_helpers.py` | `ale/io/incremental_pull.py` | Async port |
| `monitor.py` (rate-limit detector) | (deferred — RUNTIME_HARDENING_TODO #2) | Not yet ported |
| `events.py` | `ale/core/types.py:Phase` + `ale/runner/lifecycle.py:_classify_error` + `RunWriter.emit_event` | Split: phase enum vs error category vs event sink |
| `force_timeout.py` | (deferred — TODO Z.8) | Cancel hook |
| `task_loader.py` | `ale/core/loader.py` + `ale/core/task_data.py` | Split: module loading vs TaskDataSpec |
| `task_env.py` | `ale/core/env.py` | Wrapped in OpenEnv Environment contract |
| `config.py` (GCP / paths / capacity) | `ale/runner/spec.py` + `ale/providers/gcs_direct.py` + `ale/core/task_data.py` | Split per concern |
| `state.py` (Postgres) | — | Dropped |
| `registry.py` (web token / SQL) | `ale/registry.py` (env_id → AgenthleEnv factory) | Repurposed name — different semantics |
| `deployers/claude_code.py` (~800 LOC) | `ale/agents/claude_code/deployer.py` (~400 LOC) | Boilerplate moved to framework |
| `deployers/ale_claw.py` (~500 LOC) | `ale/agents/ale_claw/deployer.py` (~400 LOC) | Same harness vendored |
| `deployers/{openclaw_cli,gemini_cli,codex,...}` | (not yet ported) | Add as future commits |
| `deployer_base.py` | `ale/agents/base.py:BaseAgentDeployer` | Contract redesigned (see §3) |

---

## 2. Lifecycle / phases

### 2.1 simprun's lifecycle (from `runner.py:212-265`)

```
_phase0_provision      → gcloud create + wait_cua_ready
_phase1_start          → ensure_data_disk + stage_input + stage_eval + task_env.setup
_phase2_agent          → deployer.ensure_ready + deployer.run_agent (blocking poll loop)
_phase3_evaluate       → stage_reference + task_env.evaluate
_phase4_cleanup (always) → upload_output + delete/stop VM
```

Each `_phaseN_*` is an explicit method on `SimpRunRunner`. State transitions
through `RunState` enum, written to Postgres via `engine.py`.

### 2.2 ALE's lifecycle (from `ale/runner/lifecycle.py:run_one_unit`)

```
[ async with provision_sem ]                           # phase: env_start
    env.reset_async(variant_index=...)
      ├─ provider.acquire(spec)                        # env_start
      ├─ data_staging.ensure_data_disk + ensure_gcs_auth
      ├─ data_staging.stage_input + stage_eval         # stage_inputs
      └─ lt.start_fn(cb_task, session)                 # task_setup

[ async with run_sem ]
    asyncio.create_task(incremental_pull_loop(...))    # vm runtime only
    executor.run_deployer(deployer_cls, runtime, ...)  # agent_run
    # post-launch fan-out (concurrent via asyncio.gather):
    asyncio.gather(
      _origin_log_pipeline,                            # agent_run (pull + parse)
      _output_pipeline,                                # agent_run (output mirror)
      env.step_async(Submit())                         # stage_reference + evaluation
    )

[ except (KeyboardInterrupt / Exception) ]
    _best_effort_full_gather                           # cancel-safe pull

[ finally ]
    asyncio.wait_for(env.close_async(), 60.0)
      └─ data_staging.upload_output                    # cleanup
      └─ provider.release                              # cleanup
```

Phase taxonomy in `ale/core/types.py:Phase`:
```python
Phase = Literal[
    "env_start",        # provider.acquire + cua ready + ensure_data_disk
    "stage_inputs",     # input/software/eval rsync (agent-visible)
    "task_setup",       # @cb.setup_task user code
    "agent_run",        # executor.run_deployer + log gather
    "stage_reference",  # reference rsync (HIDDEN until eval — visibility rule)
    "evaluation",       # @cb.evaluate_task user code
    "cleanup",          # close + upload_output
    "unknown",
]
```

`AgenthleEnv.current_phase` is updated as the env walks through sub-phases.
`lifecycle._resolve_phase(env, lifecycle_phase)` prefers env's value when
the env was active, else falls back to lifecycle's own coarse tracker.

### 2.3 Diff

| Thing | simprun | ALE |
|---|---|---|
| Phase count | 5 | 7 (split `task_setup` out of staging, split `stage_reference` out of evaluate) |
| Phase boundary tagging | `RunState` enum + Postgres transitions | Plain `Phase` literal in events.jsonl + run.json.termination.phase |
| Where data staging lives | `runner._phase1_start` (input/eval) + `runner._phase3_evaluate` (reference) | `env.reset_async` + `env.step_async(Submit)` (same split but inside env contract) |
| Cancel safety | Phase 4 cleanup runs on KeyboardInterrupt | Lifecycle has `_best_effort_full_gather` + `close_async` wrapped in `wait_for(60)` |
| Background tasks during agent_run | Inline polling in deployer.run_agent | `asyncio.create_task(incremental_pull_loop)` + asyncio.gather for fanout |
| Concurrency between origin_log / output / evaluate | Sequential (post-agent) | All three concurrent via `asyncio.gather(return_exceptions=True)` |

---

## 3. Agent deployer contract

### 3.1 simprun (DeployerBase + ClaudeCodeDeployer)

```python
class DeployerBase:
    def __init__(self, vm_config: RemoteVMConfig, config): ...
    def require_prerequisites(self) -> None: ...     # binary checks
    def ensure_ready(self) -> None: ...              # heal state, write configs
    def run_agent(
        self, message: str, timeout: float,
        raw_output_dir: str | None = None,
    ) -> dict: ...                                   # SYNCHRONOUS, blocking poll
```

The deployer holds `vm_config` (server URL + os_type), drives the VM via
`run_remote(vm_config, cmd, timeout=N)` (a sync wrapper around
`requests.post`). `run_agent` is a blocking call that:
- writes runner.sh + launcher.sh to VM
- `bash launcher.sh` via run_remote
- enters its own poll loop, syncing transcript every 180s

### 3.2 ALE (`BaseAgentDeployer`)

```python
class BaseAgentDeployer(abc.ABC):
    supported_runtimes: ClassVar[frozenset[str]] = frozenset()
    hot_artifacts: ClassVar[tuple[str, ...]] = ()

    def __init__(self, runtime: AgentRuntime):
        self.runtime = runtime
        self.config = runtime.config

    @abc.abstractmethod
    async def install(self) -> None: ...
    @abc.abstractmethod
    async def launch(self, prompt: str) -> AgentRunResult: ...
    @classmethod
    @abc.abstractmethod
    def parse_artifacts(cls, *, work_dir, config, run_result, builder) -> None: ...

    @property
    def version(self) -> str | None: return None
```

### 3.3 Diff

| Aspect | simprun | ALE |
|---|---|---|
| Sync vs async | Sync `run_agent` | Async `install` + `launch` |
| Where deployer runs | Always in host (drives VM via sync HTTP) | `supported_runtimes` declares vm / local / docker; framework places it accordingly |
| Log pull responsibility | Deployer's poll loop syncs transcript every 180s | Framework's `IncrementalPuller` ticks every 15s (vm runtime); deployer just writes locally |
| Final parse responsibility | Embedded in `run_agent` (returns shaped dict) | `parse_artifacts` classmethod runs separately on host AFTER work_dir is gathered |
| Hot file declaration | Hardcoded list inside deployer | `hot_artifacts: ClassVar[tuple[str,...]]` on deployer class — framework reads it |
| Auth via env vars | Inline `export X=...` with `config.openrouter_api_key` value | Same pattern (matches simprun L375-382); values read from `os.environ` at launch time, NOT from config |
| Return shape | dict with status / output_text / interaction_log / ... | `AgentRunResult` (status / transcript_path / stderr_path / pid / exit_code / duration_s / error) — much smaller; ATIF parsing happens later |
| Concurrent per-process safety | Mutating `os.environ` in process was OK (each task = own subprocess) | Same patterns in `local` runtime would race; resolved by reading os.environ at launch, no patching (Commit E) |

---

## 4. Provider abstraction

### 4.1 simprun (`vm.py`)

Free functions:
```python
async def create_vm(name, image_cfg, machine_type, ...) -> ProvisionedVM
async def wait_cua_ready(cua_url, os_type, timeout=600, ...) -> bool
async def delete_vm(name, zone, project=...) -> bool
async def stop_vm(name, zone, project=...) -> bool
```

Caller (`runner._phase0_provision`) glues these together: create → poll IP →
wait cua ready → stash result on `self._vm: ProvisionedVM`.

### 4.2 ALE (`Provider` ABC + `GCSDirectProvider`)

```python
class GCSDirectProvider(Provider):
    async def acquire(self, spec: EnvSpec) -> VMHandle:
        instance_meta, used_zone = await self._gcloud_create_multi_zone(...)
        external_ip = self._extract_external_ip(instance_meta) or await self._describe_external_ip(name, used_zone)
        await self._wait_cua_ready(external_ip, spec.os)
        return VMHandle(id=name, endpoint=..., os=spec.os, metadata={...})

    async def release(self, vm, *, mode="delete"): ...
    def open_session(self, vm) -> cb.DesktopSession: ...
```

### 4.3 What's shared, what's different

| Detail | simprun | ALE |
|---|---|---|
| `--zone` | `image_cfg.zone` + fallback list | `cfg.zone` + `fallback_zones` (✓ Commit 21fd7ba) |
| `--machine-type` | `profile.machine_type` (CapacityProfile abstraction) | `cfg.machine_type` (single per provider) |
| `--image` | `image_cfg.image_name` | `cfg.resolve_image(spec.snapshot)` (map snapshot → image) |
| `--image-project` | `={project}` (✓ since 21fd7ba) | `={project}` (Commit 21fd7ba) |
| `--boot-disk-size` | `image_cfg.boot_disk_gb` | `cfg.boot_disk_gb` |
| `--boot-disk-type` | `_resolve_disk_type(machine_type, profile.boot_disk_type)` | `cfg.boot_disk_type or _derive_boot_disk_type(cfg.machine_type)` (Commit 163f588) |
| `--network` / `--subnet` | `image_cfg.network` / `image_cfg.subnet` | `cfg.network` / `cfg.subnet` |
| `--tags` | `agenthle-simprun` | `cfg.network_tag` (default `ale-runner`) |
| `--labels` | `purpose=agenthle-simprun, ...` | `purpose=ale, snapshot=<safe>` |
| `--create-disk` (data disk) | `name=...-data, size=200GB, type=resolved` | Same |
| `--accelerator` (GPU) | conditional on `image_cfg.gpu` | **NOT PORTED** (no GPU tasks yet) |
| `--maintenance-policy=TERMINATE` (GPU) | conditional | **NOT PORTED** |
| `--enable-display-device` (Windows) | conditional | **NOT PORTED** |
| `--service-account` | not used | optional via `cfg.service_account` |
| `--scopes` | not used | optional via `cfg.scopes` (default `cloud-platform`) |
| `--quiet` | not used | yes (suppress confirmation prompts) |
| Multi-zone fallback | per CapacityProfile.zones | `fallback_zones` list (single profile) |
| Capacity profile fallback | yes (multiple machine_types) | **NOT PORTED** (1 provider = 1 machine_type) |
| Transient retry | 3 attempts × 15/30/60s exp backoff (`_GCP_RETRYABLE_TRANSIENT`) | Same (✓ Commit e396ad7) |
| Capacity error | classified separately, triggers profile/zone next | Same (`_classify_gcloud_error → "capacity"`) |
| `wait_cua_ready` strategy | `echo ok` via /cmd SSE, N consecutive successes (=2), 600s timeout, 10s poll | Same (port at `_wait_cua_ready`) |
| Probe transport | `requests.post` (sync, wrapped in `asyncio.to_thread`) | `httpx.AsyncClient` (async-native) |

### 4.4 VMHandle vs ProvisionedVM

simprun's `ProvisionedVM` carries `name / zone / project / external_ip / machine_type / os_type / cua_url / capacity_profile / boot_disk_type / data_disk_type`.

ALE's `VMHandle` carries `id / endpoint / os / metadata: dict`. The
metadata dict holds `zone / project / image / external_ip / snapshot / backend`.
Same info, freer schema.

---

## 5. Data staging

This is the area where ALE is closest to simprun — we ported behaviour
verbatim (just async).

### 5.1 simprun primitives (`data.py`)

```python
ensure_data_disk(vm_config, os_type)            # linux: discover sdb + format + mount
                                                # windows: bring E: online + initialize
_ensure_gcs_auth(vm_config, os_type)            # upload SA key + gcloud auth activate
stage_input(vm_config, task_data, os_type)      # gsutil rsync input + software, ensure output dir
stage_eval(vm_config, task_data, os_type)       # gsutil rsync eval scripts (if eval_gcs_prefix set)
stage_reference(vm_config, task_data, os_type)  # gsutil rsync reference (eval-only)
upload_output(vm_config, task_data, os_type, run_id)  # gsutil cp output → results bucket
```

Plus internal: `_run_on_vm` (3-retry + 10s backoff + `_NO_RETRY_PATTERNS`
short-circuit), `_gcs_rsync_cmd` (linux + windows shell formatting),
`_gcs_prefix_exists` (pre-flight `gsutil ls`), `_rsync_staged_dir`
(rsync + `_verify_nonempty_dir_cmd` post-check).

### 5.2 ALE port (`ale/io/data_staging.py`)

Function-for-function port. Differences:

| Item | simprun | ALE |
|---|---|---|
| Transport | `run_remote` (sync HTTP wrapped) | `session.run_command(cmd, check=False)` (async, no per-call timeout — cua-bench rejects `timeout=` kwarg; SSE keeps connection open for long ops) |
| `_run_on_vm` retry | 3 × 10s linear | Same |
| `_NO_RETRY_PATTERNS` | matches "matched no objects" etc | Same exact list |
| SA key local path | hardcoded `<REPO_ROOT>/.gcp_key.json` | `ALE_GCS_SA_KEY_PATH` env var |
| SA key VM path | `/tmp/.gcp_key.json` (linux), `C:\tmp\.gcp_key.json` (win) | Same |
| `gcloud auth activate-service-account` | Same | Same |
| GCS task data bucket | hardcoded `gs://agenthle` | `ALE_GCS_TASK_DATA_BUCKET` env var, default `gs://agenthle` |
| GCS results bucket | hardcoded `gs://agenthle-run-results` | `ALE_GCS_RESULTS_BUCKET` env var, same default |
| `vm_data_root` | linux `/media/user/data/agenthle`, win `E:\agenthle` | Same |
| `vm_subdir(os, dom, task, var, sub)` | Same convention | Same (`ale/core/task_data.py`) |
| `gcs_task_prefix(dom, task, var)` | `<BUCKET>/{dom}/{task}/{var}` | Same |
| `_gcs_rsync_cmd` linux | `mkdir -p '{dst}' && gsutil -m rsync -r '{src}' '{dst}'` | Same verbatim |
| `_gcs_rsync_cmd` win | powershell `New-Item ... | gsutil -m rsync ...` | Same verbatim |
| `_verify_nonempty_dir_cmd` | `test -d && find ... -mindepth 1 -print -quit \| grep -q .` | Same |
| `_repair_linux_data_root_cmd` | `sudo mkdir + chown + test -w` | Same |
| `_linux_data_disk_find_cmd` | discover via candidates + lsblk + readlink | Same (port at `_ensure_linux_data_disk`) |
| `_linux_data_disk_prep_cmd` | fstab defang + systemctl daemon-reload + 3-pass swapoff/umount + wipefs + blockdev + mkfs.ext4 (3 retries) | Same (✓ Commit a862a66) |
| `_dismiss_format_dialog` (windows) | WScript.Shell ESC | Same (✓ Commit a862a66) |
| `_ensure_windows_data_disk` | online offline disk → initialize raw → format NTFS letter=E | Same |
| `stage_input` files set | input, software, output | Same: input/, software/ (chmod +x), ensure output/ dir |
| `stage_eval` gating | `eval_gcs_prefix AND eval_dir` both set in metadata | Same |
| `stage_reference` | called explicitly from `_phase3_evaluate` BEFORE evaluate | Called explicitly inside `env.step_async(Submit)` BEFORE evaluate (visibility rule) |
| Visibility rule | Implicit (task author must not stage reference in setup) | Explicit + guarded by `tests/smoke_data_staging.py` source-grep |
| `upload_output` | `gcloud storage cp -r src dst` | Same |
| `requires_task_data` detection | metadata flag OR implicit from input_dir presence | metadata flag OR `config.REQUIRES_TASK_DATA` — implicit heuristic DROPPED (caused demo/hello false positive) |

### 5.3 What's NOT carried over

- simprun's task_loader implicitly inferred `requires_task_data=True` if
  `metadata["input_dir"]` was set. We dropped that — explicit only — because
  `LinuxTaskConfig.to_metadata()` always sets `input_dir`, which gave
  demo/hello a false positive (it doesn't need GCS).
- simprun's `data.py` parameter names `timeout=N` (kept by callers) are now
  decorative — cua-bench session.run_command ignores them. Stayed in
  `_run_on_vm`'s signature as caller intent doc only.

---

## 6. Log pipeline (incremental pull, gather, mirror)

### 6.1 simprun (claude_code deployer + sync_helpers + remote)

Inside `claude_code.run_agent`'s poll loop:
```
loop:
  time.sleep(10)
  if elapsed - last_sync >= 180:   # sync_interval
    if local_transcript_size > 5MB:
       _sync_incremental(...)       # range-pull via download_file_range
    else:
       _sync_agent_output(...)      # full download_file per target
final:
  _sync_agent_output(final=True)    # full + _verify_final_sizes
```

`download_file_range` (in `remote.py`): single round-trip command
`stat -c%s + tail -c +N | head -c M | base64 -w0` returning `SIZE=<n>\nB64=<...>`,
parsed client-side. JSONL-boundary safety via `apply_jsonl_boundary` (cut at
last `\n`).

Per-target `RangeState`: offset (only advances after fsync), last_remote_size,
consecutive_errors, rotation_count.

### 6.2 ALE (`ale/io/incremental_pull.py`)

Async port. Differences:

| Item | simprun | ALE |
|---|---|---|
| Where invoked | Inside deployer's blocking poll loop | Background `asyncio.Task` started by lifecycle before `executor.run_deployer` |
| Tick interval | 180s (3 min) | 15s (DEFAULT_INTERVAL_S) |
| 5MB gate | Yes (>5MB switches periodic to incremental) | No gate — always incremental during agent_run (matches simprun's behaviour above the gate) |
| Targets | Hardcoded in deployer | `deployer_cls.hot_artifacts: ClassVar[tuple[str,...]]` |
| Per-call retry | 3 × 1/3/9s backoff inside `download_file_range` | Same in `_pull_range` |
| `RangeState` semantics | Identical | Identical |
| JSONL boundary | `apply_jsonl_boundary` | Same |
| Rotation handling | nuke local + reset state | Same |
| Missing-file handling | nuke local + reset state | Same |
| Final reconcile | `_verify_final_sizes` (1 retry full download on size mismatch) | `IncrementalPuller.reconcile_final` (one tick + up to 3 top-up retries via apply_range_step on size mismatch — Commit 70940d4) |
| Cancel-safe gather | Implicit (deployer's poll loop catches signal) | Explicit `_best_effort_full_gather` in lifecycle's except blocks (ArtifactMirror full pull, 60s bounded) |

### 6.3 ArtifactMirror (NEW, no simprun equivalent)

`ale/io/artifact_mirror.py:ArtifactMirror.pull_dir(session, vm_path, dest_rel)`:
- GCS bridge primary (VM-side `gsutil cp -r` → host-side `gsutil cp -r`)
- CUA-direct fallback (walks via `session.list_dir` + `read_bytes`)
- Per-file size cap (50MB → head+tail 25MB via dd + `.truncated` marker JSON)
- Per-file 3-retry with 1/3/9s backoff
- Directory probe via `test -d` BEFORE attempting file read (was previously
  inferred from a failed read, which mis-recursed)

Used for `origin_log` (deployer work_dir pull) and `output` (task remote_output_dir pull).
Both run concurrently with `evaluate()` via `asyncio.gather` in lifecycle's
fanout block.

---

## 7. Concurrency model

### 7.1 simprun

`engine.py`:
- outer: `Semaphore(max_in_flight)` — bounds *task assignment* (DB
  in-flight count)
- semaphore held ONLY during run, NOT during VM acquire (so slow acquire
  doesn't starve assignment)

`batch.py`:
- inner: `ThreadPoolExecutor(max_workers=concurrency)` — runs the
  blocking `simprun.runner` per task

Two-layer because simprun was sync-blocking; threads + Postgres assignment
were the way to scale.

### 7.2 ALE

`ale/runner/runner.py:Runner.run`:
- `provision_sem = asyncio.Semaphore(spec.provision_concurrency or spec.run_concurrency)`
- `run_sem = asyncio.Semaphore(spec.run_concurrency)`
- Each unit holds `provision_sem` ONLY during `env.reset_async`
  (provider.acquire + data staging + setup), releases it BEFORE entering
  `run_sem` for launch + fanout + eval
- Single `asyncio.gather` drives all units

| Knob | simprun | ALE |
|---|---|---|
| Provision-side sem | `max_in_flight` (engine) | `provision_concurrency` (default = run) |
| Run-side sem | `max_workers` (ThreadPoolExecutor) | `run_concurrency` |
| Behaviour when provision slow | Run-sem free; new assignments enter, sit in acquire | Same; new units enter provision, sit in run_sem after acquire |
| Default | max_in_flight=10, max_workers=20 | both default to 1 (sequential) |

### 7.3 Removed semantic

simprun's `concurrency` (max_workers) was concurrency of OS threads driving
blocking simprun.runner. With ALE being async, "concurrency" = number of
concurrent asyncio coroutines, capped by `run_sem`. No threads involved.

---

## 8. Error handling / phase + category

### 8.1 simprun (`events.py:classify_error`)

```python
class ErrorCategory(str, Enum):
    INFRASTRUCTURE = "infrastructure"
    STAGING = "staging"
    AGENT = "agent"
    EVALUATION = "evaluation"
    UNKNOWN = "unknown"

def classify_error(phase, error_message) -> ErrorCategory:
    if phase in ("staging_input", "staging_eval", "staging_reference", "uploading_output"):
        return ErrorCategory.STAGING
    # ... pattern matching on error message ...
```

Phase-based classification, with some message-pattern overrides.

### 8.2 ALE

Split into TWO orthogonal fields in `run.json.termination`:

```jsonc
"termination": {
  "reason": "failed",
  "phase": "agent_run",        // ale.core.types.Phase — WHERE failed
  "category": "auth_failed",   // WHY failed (operator action class)
  "error": {"type": ..., "message": ..., "traceback": ...}
}
```

Phase resolution (lifecycle's `_resolve_phase`):
- Prefer `env.current_phase` if env was active (more granular: env_start /
  stage_inputs / task_setup / stage_reference / evaluation / cleanup)
- Fall back to lifecycle's own coarse tracker (covers agent_run + custodial
  work outside env.reset/step)

Category (lifecycle's `_classify_error`, 6 buckets):
```python
("rate_limited", ("rate limit", "ratelimit", "429", "too many requests")),
("vm_quota_exhausted", ("quota", "stockout", "resource_exhausted", ...)),
("auth_failed", ("401", "403", "authentication_failed", "permission denied",
                 "unauthorized", "forbidden", "llm auth failed",
                 "user not found", "invalid api key")),
("gcs_missing", ("matched no objects", "no urls matched",
                 "bucketnotfoundexception", "no such object")),
("transport_error", ("connection reset", "connection refused", "503",
                     "service unavailable", "deadline exceeded", ...)),
("rpc_timeout", ("timeout", "timed out")),
```

`KeyboardInterrupt` / `CancelledError` → category=None (cancel doesn't need
a category; phase tells you what was interrupted).

### 8.3 Diff

| Aspect | simprun | ALE |
|---|---|---|
| Phase tag location | Postgres + events.jsonl | run.json.termination.phase + events.jsonl |
| Phase × category orthogonal | No (single ErrorCategory) | Yes |
| Phase granularity | 5 phases | 7 phases |
| Category bucket count | 5 | 6 (split rpc_timeout from rate_limited) |
| Where pattern matches live | events.py | lifecycle.py:_CATEGORY_PATTERNS |

---

## 9. Resume / skip-completed

| Aspect | simprun | ALE |
|---|---|---|
| Default | `--skip-completed=True` | Default ON (same) |
| Override | `--force-rerun` | Same flag name |
| Resume key | Match on `(domain, task, variant)` from output dir | Match on `(agent_id, task_path, variant_index)` from prior run.json |
| What "completed" means | `status in {"completed", "timeout"}` | Same |
| Failed/cancelled | Re-run | Re-run |
| Output dir overlap | New run uses new timestamp dir; old logs untouched | Same |
| Latest-timestamp resolution | Latest wins (so "completed then failed" re-runs) | Same (✓ explicit test in `smoke_resume.py`) |
| Trigger by | Same output dir (typically `<output_root>/<exp_name>/`) | `ExperimentSpec.name` matches (output root is `<output.root>/<name>/`) |

Implementation:
- simprun: walks output dir for `task_status_latest.json` or per-task `summary.json`
- ALE: walks for `run.json`, reads `status` field

---

## 10. Env vars / secrets

### 10.1 simprun

API keys passed via `api_keys` field in agent config yaml:
```yaml
agent:
  api_keys:
    OPENROUTER_API_KEY: ${env:OPENROUTER_API_KEY}
```

Deployer config dataclass holds these as fields, passes to bash runner as
`export X='<value>'`.

GCP credentials: hardcoded `<REPO_ROOT>/.gcp_key.json` path.

### 10.2 ALE

API keys NEVER in yaml or config. Operator sets in shell:
```bash
source .env   # .env is gitignored; .env.example is the template
```

Framework reads at runtime:
- `local` runtime: deployer reads `os.environ` directly (litellm picks up
  itself)
- `docker` runtime: `--env-file` written from `collect_host_env()` →
  container inherits
- `vm` runtime: `spec.host_env` shipped via python_exec → `_vm_entry`
  does `os.environ.update(...)` before deployer construction

Propagated set (`ale/runtime/_env.py:PROPAGATED_ENV_VARS`):
```python
("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
 "OPENROUTER_API_KEY", "OPENAI_API_KEY", "BRAVE_API_KEY")
```

Other env-driven config:
| Var | Purpose | simprun equivalent |
|---|---|---|
| `ALE_GCS_SA_KEY_PATH` | local SA key path (uploaded to VM for gsutil auth) | hardcoded `<REPO_ROOT>/.gcp_key.json` |
| `ALE_GCS_TASK_DATA_BUCKET` | input data bucket | hardcoded `gs://agenthle` |
| `ALE_GCS_RESULTS_BUCKET` | output upload bucket | hardcoded `gs://agenthle-run-results` |
| `ALE_ARTIFACT_GCS_BUCKET` | GCS bridge bucket for ArtifactMirror | n/a (no bridge) |
| `ALE_ARTIFACT_GCS_KEY_FILE` | local SA for artifact mirror gsutil | n/a |
| `ALE_ARTIFACT_GCS_VM_KEY_FILE` | VM-side SA for artifact mirror gsutil | n/a |
| `AGENTHLE_CREDENTIALS_DIR` | local dir for task-declared `requiredCredentials` | same name (BaseTaskSetup) |

### 10.3 Why this changed

simprun ran in trusted host context — putting `${env:...}` in yaml was a
ceremony, not a security boundary. Multi-key rotation was per-Postgres-task.

ALE concurrent-units in one process led to the `_patched_environ` bug:
mutating global `os.environ` from concurrent asyncio coroutines clobbered
each other. Switching to "read at launch, inline into bash, never mutate
global env" eliminated the class of bug + the yaml-secret ceremony.

---

## 11. Runtime abstraction (NO simprun equivalent)

The biggest architectural addition. simprun has ZERO concept of "where the
deployer code runs" — it's always "host process driving VM via sync HTTP".

ALE's three runtimes:

### 11.1 vm runtime
- Deployer's `install()` / `launch()` run INSIDE the eval VM
- Framework ships the deployer source via `VmExecutor` (scp ale subtree)
  + `cua.python_exec(run_deployer_in_vm, spec)`
- The VM-side Python's `subprocess.run` calls execute on the VM
- Used by claude_code (CLI binary lives in VM, makes sense to drive it
  locally)
- `hot_artifacts` get incremental-pulled from VM to host every 15s

### 11.2 local runtime
- Deployer's `install()` / `launch()` run in host Python process
- Drives VM via cua-bench session (RPC)
- Used by ale_claw (OpenClaw harness imports as in-process library — would
  be lossy to ship 5000 LOC of harness into VM)
- No incremental pull (work_dir is on host disk)

### 11.3 docker runtime
- Deployer's `install()` / `launch()` run in host docker container
- Same code as local; just sandboxed via `ale/native-base:0.1.0` image
- Bind mount `<host_run_dir>:/work` so work_dir is host-visible
- `--env-file` propagates host shell env vars into container
- Used by ale_claw when isolation matters more than speed

### 11.4 Executor + Runtime split

`ale/runtime/`:
- `base.py:AgentRuntime` — passive context dataclass (work_dir, vm_endpoint,
  vm_os, config, kind)
- `local.py:LocalRuntime`, `vm.py:VmRuntime`, `docker.py:DockerRuntime` —
  subclasses with kind-specific path conventions
- `executor.py:Executor` ABC + `EXECUTORS` registry
- `local_executor.py:LocalExecutor`, `vm_executor.py:VmExecutor`,
  `docker_executor.py:DockerExecutor` — strategies that place + run the
  deployer

Lifecycle dispatch: `EXECUTORS[runtime_kind].run_deployer(deployer_cls,
runtime, prompt, timeout_s)`.

---

## 12. Detail-level parameter changes

### 12.1 Timeouts

| Op | simprun | ALE |
|---|---|---|
| `wait_cua_ready` total | 600s | 600s (`cfg.ready_timeout_s`) |
| `wait_cua_ready` poll interval | 10s | 10s (`cfg.ready_poll_interval_s`) |
| Stable successes required | 2 | 2 (`cfg.ready_stable_successes`) |
| Probe HTTP client | 10s | 10s (httpx.AsyncClient) |
| `gcloud compute instances create` | 600s (subprocess) | 600s (asyncio subprocess) |
| Agent total (`timeout_s`) | per-task default 7200s, per-agent override | `BaseAgentConfig.timeout_s = 1800.0`; yaml override per agent |
| `evaluate()` budget | none — sat inside `_phase3` | `ExperimentSpec.eval_timeout_s = 3600.0`; wraps `evaluate_fn` in `asyncio.wait_for` |
| `close_async` (VM release) | no explicit cap | hardcoded 60s `asyncio.wait_for` (lifecycle finally) |
| Best-effort full gather on cancel | n/a | hardcoded 60s |
| `IncrementalPuller` per-range RPC | n/a (sync) | implicit (cua-bench SSE); 3 retries with 1/3/9s backoff |
| `data._run_on_vm` retry | 3 × 10s linear | Same (10s linear, 3 attempts) |
| `data._rsync_staged_dir` timeout | 1800s | 1800s (decorative; cua-bench ignores) |
| GCP create retry | 3 × 15/30/60s exp backoff (transient) | Same |
| GCS bridge gsutil pull | 600s | 600s (`asyncio.wait_for`) |

### 12.2 Disk / resource limits

| Item | simprun | ALE |
|---|---|---|
| Boot disk size | per-image (`image_cfg.boot_disk_gb`) | `cfg.boot_disk_gb = 50` (default), per-config |
| Boot disk type | `_resolve_disk_type` (family-based) | `cfg.boot_disk_type or _derive_boot_disk_type(machine_type)` |
| Data disk size | hardcoded 200GB in `_build_create_args` | `cfg.data_disk_gb = 200` |
| Data disk type | `_resolve_disk_type` (family-based) | `cfg.data_disk_type = "pd-balanced"` |
| Linux data root | `/media/user/data/agenthle` | Same |
| Windows data root | `E:\agenthle` | Same |
| ArtifactMirror per-file cap | n/a (no mirror) | 50MB → head+tail 25MB via dd |
| Docker container memory | n/a | `--memory 4g --cpus 2` (hardcoded) |

### 12.3 Polling intervals

| Where | simprun | ALE |
|---|---|---|
| Agent poll loop (claude_code) | 10s (sync time.sleep) | 5s (`claude_code/deployer.py:poll_interval`) |
| Periodic transcript sync | 180s | n/a (incremental every 15s) |
| Incremental pull tick | n/a (inline in 180s sync) | 15s (`DEFAULT_INTERVAL_S`) |
| GCP IP poll fallback | 5s for 120s | same (`_describe_external_ip` settle 5s) |
| State heartbeat | 20s (`engine._batch_heartbeat_loop`) | n/a (no DB) |

### 12.4 Retry counts

| Op | simprun | ALE |
|---|---|---|
| gcloud transient retry | 3 (`_GCP_MAX_RETRIES_TRANSIENT`) | 3 (`_GCP_MAX_RETRIES`) |
| `_run_on_vm` (data staging) | 3 (`_MAX_RETRIES`) | Same |
| `download_file_range` | 1 (no retry in remote.py) | 3 (1/3/9s — `_RANGE_RETRIES`) |
| ArtifactMirror per-file read | n/a | 3 (1/3/9s — `_READ_RETRIES`) |
| `mkfs.ext4` | 3 × 5s | 3 × 5s |
| `wait_cua_ready` stable successes | 2 | 2 |

---

## 13. What we explicitly did NOT port

### 13.1 Capacity profile abstraction
simprun: `CapacityProfile(name, priority, machine_type, zones)` with multiple
profiles tried in order — supports e.g. "try c4 first, fall back to n2".
ALE: single `machine_type` per provider, only zone fallback. Adding profiles
later is feasible (extend `_gcloud_create_multi_zone` to iterate profiles ×
zones), but not needed for current scale.

### 13.2 GPU support
simprun has `--accelerator=type=nvidia-tesla-...` + `--maintenance-policy=TERMINATE`
+ `is_accelerator_machine_type` check (a2/a3 bundle GPU into machine_type).
Not ported; ALE doesn't have GPU tasks yet.

### 13.3 force_timeout
simprun's `force_timeout.py` writes a sentinel file to VM that the deployer
polls; allows external "cancel this task" without killing the runner.
Not ported (would re-introduce in CuaHouseProvider if/when we have one).

### 13.4 Rate-limit monitor
simprun's `monitor.py:RateLimitDetector` runs as background thread, tails
stderr.log, fires on 3 rate-limit matches in 60s window → cancels agent.
Not ported (RUNTIME_HARDENING_TODO #2). Likely needed before scaling to
700+ tasks.

### 13.5 Postgres state + web console integration
simprun's `state.py` + `engine.py` write run metadata + task assignment to
Postgres; `web_console/` reads it. ALE is operator-facing only — `run.json`
on disk replaces.

### 13.6 12 deployer ports
simprun has `deployers/{claude_code, codex, gemini_cli, openclaw_cli,
ale_claw, manus, simular, computer_use_demo, ...}`. ALE has just
`claude_code` and `ale_claw`. Adding others is straightforward (the
runtime + executor abstraction makes it boilerplate-free) but is future
work.

### 13.7 `simprun` external runner adapter
For agents that run inside cua-house leased VMs via `external/` module.
ALE will need a `CuaHouseProvider` to do this — currently stubbed.

---

## 14. Open gaps / TODO

See also `docs/RUNTIME_HARDENING_TODO.md`. Items that touch simprun-parity:

| Item | What's missing | Where |
|---|---|---|
| Rate-limit monitor | port `monitor.py:RateLimitDetector` + cancel hook | `RUNTIME_HARDENING_TODO #2` |
| Cleanup mode (delete/stop/keep) | yaml knob; Provider.release already supports it | `RUNTIME_HARDENING_TODO #6` |
| Atomic write run.json/trajectory.json | `os.replace` pattern | `RUNTIME_HARDENING_TODO #5` |
| Provider sweep CLI | offline tool for dangling VMs | `RUNTIME_HARDENING_TODO #9` |
| Force-timeout / external cancel | simprun's force_timeout.py | TODO Z.8 (deferred) |
| Capacity profile abstraction | multi-machine_type per provider | TODO §13.1 |
| GPU args | `--accelerator` + `--maintenance-policy` | TODO §13.2 |
| CuaHouseProvider | port simprun's external runner adapter | TODO §13.7 |
| Per-RPC timeout | cua-bench's session.run_command lacks it | inherent to cua-bench (waiting for upstream) |

---

## 15. File-level index

Source of truth for cross-checking:

### simprun (`agenthle/scripts/web_console/lib/simprun/`)
- `runner.py` — per-task orchestrator (4 phases)
- `batch.py` — multi-task driver + ThreadPoolExecutor
- `engine.py` — task assignment + Postgres state machine
- `vm.py` — gcloud / cua probe
- `data.py` — disk + GCS staging
- `remote.py` — sync HTTP transport, download_file_range
- `sync_helpers.py` — range state + JSONL boundary
- `monitor.py` — rate-limit detector
- `events.py` — event logger + classify_error
- `force_timeout.py` — cancel hook
- `state.py` — Postgres
- `registry.py` — web console auth
- `config.py` — paths + capacity + image table
- `task_loader.py` — task module loader + TaskDataSpec
- `task_env.py` — session ctor + setup/evaluate dispatch
- `deployer_base.py` + `deployers/*.py` — 12 agents

### ALE (`agents-last-exam/`)
- `ale/cli.py` — `python -m ale run experiments/...`
- `ale/runner/{loader,spec,factory,runner,resume,lifecycle}.py` — orchestrator stack
- `ale/core/{env,loader,provider,task_data,types,cmd_result}.py` — env + provider + types
- `ale/providers/{gcs_direct,static}.py` — Provider impls
- `ale/runtime/{base,local,vm,docker,executor,local_executor,vm_executor,docker_executor,_env,_vm_entry,_docker_entry,Dockerfile.native_base}.py` — Runtime abstraction
- `ale/io/{data_staging,artifact_mirror,incremental_pull,run_writer}.py` — IO layer
- `ale/agents/{base,trajectory}.py` — deployer contract + ATIF
- `ale/agents/{claude_code,ale_claw}/` — two deployers
- `tasks/{common_config,linux_runtime,common_setup}.py` + `tasks/demo/` — task library
- `tests/smoke_*.py` — unit smokes
- `tests/integration/runtime_smoke_*.py` — live VM smokes
- `experiments/` (gitignored) — operator-local yaml
- `docs/{DESIGN,AGENTS,SIMPRUN_DIFF,RUNTIME_HARDENING_TODO}.md` — design + this doc + TODO

---

End.
