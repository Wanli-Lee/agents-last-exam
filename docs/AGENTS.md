# How to add a new agent to ALE

This is the SOP for implementing a new agent deployer. Pair it with:

- `docs/DESIGN.md` — overall architecture (what `AgenthleEnv`, `Provider`, `BaseAgentDeployer` are and how they fit)
- `docs/SESSION_API.md` — the in-VM RPC surface (`computer.interface.*`) you'll use inside `install` / `launch` / `collect`
- `ale/agents/claude_code/deployer.py` — the only complete reference impl right now

> **Status**: covers in-VM agents (claude-code) and native (ale_claw / OpenClaw) end-to-end. Both reference impls in-tree. The Native cookbook (§7) is the post-mortem of the OpenClaw migration — read it before adding another native agent.

---

## 0. Pick a flavor

| Flavor | Where the agent process runs | `work_dir_on_vm` | Examples |
|---|---|---|---|
| **In-VM** (default) | Inside the guest. You stage binaries on the VM via the `computer` handle. | `True` | claude-code CLI, codex CLI, openclaw_cli |
| **Native** | On the ALE host (local subprocess, docker container, …). You use `computer` only for VM info (`os_type`, endpoint) and to give the agent process a way to reach the VM. | `False` | openhands-in-docker, host-side computer-use loops |

Two-line decision: if the agent is *one binary you can install + invoke inside the guest with stdin/argv*, go in-VM. Otherwise native.

---

## 1. File layout

```
ale/agents/<your_agent>/
├── __init__.py        # re-exports Config + Deployer
├── config.py          # <Name>Config(BaseAgentConfig)
└── deployer.py        # <Name>Deployer(BaseAgentDeployer)
```

If your deployer needs static assets that ship with the package (e.g. a vendored MCP server, a runner script template), put them in `ale/agents/_assets/<your_agent>/`.

---

## 2. Implement the Config

```python
# ale/agents/foo/config.py
from dataclasses import dataclass
from typing import ClassVar
from ale.agents.base import BaseAgentConfig


@dataclass
class FooConfig(BaseAgentConfig):
    name: ClassVar[str] = "foo"           # ← REQUIRED; goes into trajectory.agent.name + run.json
    model: str = "foo-default-model"      # override base default

    # Routing / auth
    foo_api_key: str = ""

    # Knobs the framework already gives you on BaseAgentConfig:
    #   model, max_turns, timeout_s, save_screenshots, api_keys, install_paths
    # Subclasses MAY add fields. Do NOT redefine the standard six.

    def __post_init__(self) -> None:
        if not self.foo_api_key:
            raise ValueError("FooConfig requires foo_api_key")
```

Rules:

1. `name` is a `ClassVar[str]` — class attribute, **not** an `__init__` field.
2. **Never auto-read API keys from `os.environ`** in the config. Caller (yaml, test, integration smoke) passes them explicitly. Reasons: prevents cross-experiment key leak; redaction in `run.json` works.
3. Validate at construction (`__post_init__`); fail loudly on missing required fields.
4. Use `install_paths: InstallPaths` (inherited) for any in-VM path that varies per image (node binary, agent bin dir, work dir root). Don't hardcode `/usr/local/bin/node`.

---

## 3. Implement the Deployer

```python
# ale/agents/foo/deployer.py
from typing import TYPE_CHECKING
from ale.agents.base import AgentRunResult, BaseAgentDeployer
from ale.agents.trajectory import TrajectoryBuilder
from .config import FooConfig

if TYPE_CHECKING:
    from computer import Computer


class FooDeployer(BaseAgentDeployer):
    # ★ Flip this to False for native agents.
    work_dir_on_vm = True

    def __init__(self, config: FooConfig):
        self._cfg = config

    @property
    def config(self) -> FooConfig:
        return self._cfg

    @property
    def version(self) -> str | None:
        return "@foo/cli@1.2.3"   # surfaces in trajectory.agent.version

    async def install(self, computer: "Computer") -> None:
        """Stage prereqs on the VM (verify-or-install pattern)."""

    async def launch(
        self, computer: "Computer", *, prompt: str, timeout_s: float,
    ) -> AgentRunResult:
        """Spawn the agent and wait. Always return AgentRunResult; raise only
        if even *starting* fails."""

    async def collect(
        self, computer: "Computer", run: AgentRunResult,
        builder: TrajectoryBuilder,
    ) -> None:
        """Parse on-VM logs into Trajectory Steps. Partial logs are valid;
        emit a system step and continue rather than raising."""

    def work_dir(self, computer: "Computer") -> str | None:
        """Where everything you wrote lives. None skips origin_log mirroring."""
        return self._cfg.install_paths.work_dir(computer.os_type, "foo")
```

The framework owns `run()` and `mirror_artifacts()` on the base class — you don't override them.

### 3.1 `install` — verify-or-install

The pattern: assume the image *may* be baked with your CLI, and only install when missing.

```python
async def install(self, computer):
    iface = computer.interface
    paths = self._paths(computer)

    # 1. Node (image-baked on Linux; runtime-installable on Windows)
    await ensure_node(computer, self._cfg.install_paths)

    # 2. The CLI itself
    if not await iface.file_exists(paths.cli_bin):
        await npm_install_global(computer, "@foo/cli@1.2.3", self._cfg.install_paths)
        if not await iface.file_exists(paths.cli_bin):
            raise RuntimeError(f"foo CLI still missing at {paths.cli_bin}")

    # 3. Per-run work dir + config files
    await iface.create_dir(paths.work_dir)
    await iface.write_text(paths.config_file, json.dumps({...}))
```

Helpers in `ale/agents/runtime_install.py` you can reuse:

- `ensure_node(computer, install_paths)` — verifies on Linux, downloads + extracts on Windows
- `npm_install_global(computer, "pkg@ver", install_paths)` — handles PATH for Windows npm prefix
- `upload_mcp_server(computer, install_paths)` — uploads the vendored `cua-mcp-server/` tree

Use `computer.interface.run_command(cmd)` for arbitrary shell — it returns a `CommandResult(stdout, stderr, returncode)`. **Do not** use `session.run_command` (broken; see `docs/SESSION_API.md` §13).

### 3.2 `launch` — fire-and-poll

Pattern (Linux, demonstrated in `claude_code/deployer.py`):

1. Write `prompt.txt`, `run_<agent>.sh`, and a `launch.sh` that does `setsid bash run_<agent>.sh &` then captures `$!` into a PID file.
2. The runner script redirects stdout → `transcript.jsonl`, stderr → `stderr.log`, and ends with `echo $? > done.marker`.
3. `run_command(launch.sh)` returns immediately. Poll: read `done.marker` (if present → done, classify by exit code); else check `kill -0 <pid>`; else `time.monotonic() ≥ deadline` → kill PID and return `timeout`.

Why setsid + PID file + done.marker: cua-server's HTTP `/cmd` returns when the spawned process is detached, so we can't rely on its return. PID + marker give us a robust poll surface that survives reconnects.

Always return an `AgentRunResult` even on failure (`status="failed"` + `error=...`). Diagnose from `stderr.log` tail + transcript pattern matching; see `_diagnose_failure` in `claude_code/deployer.py`.

```python
@dataclass
class AgentRunResult:
    status: str                  # "completed" | "timeout" | "failed"
    transcript_path: str | None  # for collect()
    stderr_path: str | None
    pid: int | None
    exit_code: int | None
    duration_s: float | None
    error: str | None
```

### 3.3 `collect` — log → trajectory

Steps you append must use one of:

| `source` | When | Filled fields |
|---|---|---|
| `"agent"` | One LLM turn (your CLI's "assistant" event) | `message` (text), `tool_calls`, `metrics` (tokens, cost), `extra` |
| `"environment"` | Tool result from the VM (your CLI's "tool_result"/"user" event reflecting back) | `observation.results: list[ToolResult]` |
| `"system"` | Framework note: cancellation, timeout, collect error | `message`, `extra={"reason": ...}` |

The framework has **already** seeded a `"user"` source step (the instruction) before `collect` runs. Don't duplicate it.

Reference: `ClaudeCodeDeployer._consume_assistant` / `_consume_user` for stream-json → Trajectory. Other CLIs will need their own parser but the target shape is the same.

If logs are partial / empty, emit a single `"system"` step explaining what was missing and return cleanly. Never raise out of `collect` — the framework wraps it but it's clearer if you handle it yourself.

### 3.4 `work_dir` — the mirror source

```python
def work_dir(self, computer):
    # In-VM: absolute VM path. Convention: install_paths.work_dir(os, "<agent_name>")
    return self._cfg.install_paths.work_dir(computer.os_type, "foo")
    # Native: an absolute LOCAL path you wrote to.
    # Return None to skip origin_log mirroring entirely.
```

After your run ends, the framework calls `mirror_artifacts(env, mirror)` which:

- If `work_dir_on_vm = True` → `mirror.pull_dir(computer, work_dir, "origin_log/<name>/")` (GCS bridge with cua-direct fallback)
- If `work_dir_on_vm = False` → `shutil.copytree(work_dir, run_dir/"origin_log"/<name>/)`

In either case, the task's `remote_output_dir` (always VM-side by definition) is mirrored separately to `output/`.

---

## 4. Register the agent (optional)

For yaml shortcut keys, add to `ale/runner/factory.py`:

```python
AGENT_REGISTRY: dict[str, tuple[str, str]] = {
    "claude_code": (".../ClaudeCodeDeployer", ".../ClaudeCodeConfig"),
    "foo":         ("ale.agents.foo.deployer.FooDeployer",
                    "ale.agents.foo.config.FooConfig"),
}
```

Without registration, users can still reference your deployer by fqdn in yaml:

```yaml
agents:
  - id: foo_sonnet
    class: ale.agents.foo.deployer.FooDeployer
    config: { foo_api_key: ..., ... }
```

The factory infers the config class from `__init__(self, config: FooConfig)`'s annotation.

---

## 5. Smoke test

### 5.1 Unit smoke (stubbed VM)

Copy `tests/smoke_installed_agent.py` and swap the stub deployer for yours. Use `StubProvider` + `tests/_stubs/computer.py` (a fake `Computer` with the methods you'll call). Validate:

- `reward == 1.0` on the success path
- `result.status == "completed"`
- Trajectory step sources are `["user", "agent", ...]` in order
- `result.trajectory.agent.name == "<your name>"`

### 5.2 Real-VM smoke (optional but recommended)

Copy `tests/integration/gcp_smoke.py` and:

1. Swap the `ClaudeCodeDeployer` for yours.
2. Pick an image that satisfies your prereqs (or set `work_dir_on_vm = False` and bring up the agent on the host instead).
3. Run against `demo/hello` — the simplest task. Reward should be 1.0 if your agent can call `write_text` on the VM.

Cost: ~$0.20/hour VM + your model's token cost.

---

## 6. Dos and don'ts

✅ Use `computer.interface.*` for all VM I/O. The full surface is in `docs/SESSION_API.md`.

✅ Use `computer.os_type` for OS branching. Do not parse `uname` / `ver`.

✅ Make `install` idempotent / verify-or-install — image-baked tools should be detected and skipped.

✅ Make `launch` always return `AgentRunResult`. Raise only if `setsid` itself fails.

✅ Make `collect` safe on partial / missing logs.

✅ Use `setsid + PID file + done.marker` on Linux, `Start-Process + PID + done.marker` on Windows. Don't rely on the cua `run_command` return code to know when the agent finished.

✅ Diagnose failures from `stderr.log` tail + transcript signature. Surface the diagnosis on `AgentRunResult.error`.

✅ Pin your CLI version (npm package coord with `@X.Y.Z`). Surface it via `version` property.

❌ Never auto-read API keys from `os.environ` in config. Caller passes them.

❌ Never put the API key in the runner script body unredacted if you log the script. Build env via `EnvVar` descriptors (`ale/agents/cli_flags.py`) so it's contained.

❌ Don't redefine `BaseAgentConfig`'s six standard fields (`model`, `max_turns`, `timeout_s`, `save_screenshots`, `api_keys`, `install_paths`). Override the default value with `= ...` if you want a different default.

❌ Don't reach into `env._session` / `env._lt`. Use `env.computer`, `env.task_path`, `env.vm`.

❌ Don't try to short-circuit Submit in `launch`. Your agent finishes; the framework runs `task.evaluate` separately.

---

## 7. Native cookbook

> Reference impl: `ale/agents/ale_claw/` (the OpenClaw harness — first native deployer in ALE). Read its `deployer.py` end-to-end before writing your own; this section pulls out the patterns you'll reuse.

A native deployer runs the agent process **in this Python process** (or as a host-side subprocess / container), and uses `env.session` only to drive the test VM. Set `work_dir_on_vm: ClassVar[bool] = False` so `mirror_artifacts` does `shutil.copytree(work_dir, run_dir/origin_log/<name>/)` instead of pulling from the VM.

### 7.1 Source layout — "rebuild not vendor"

If your agent's value lives in an upstream Python package (claude-code is a CLI we install at runtime; OpenClaw is a Python library we **call**), don't black-box it as a `_vendor/` blob with `sys.modules` install tricks. Instead:

1. Copy the upstream source files into `ale/agents/<your_agent>/<harness>/` (we use `harness/` for ale_claw — pick a name that makes sense).
2. Sweep imports: anywhere upstream code says `from cua_bench.agents.openclaw.X` (etc.), rewrite to `from .X` (relative within your harness/) or to your new namespace. Anything that resolves under our existing deps (`cua_bench.agents.base`, `agent.*`, `core.telemetry`) stays.
3. Drop the upstream's "wrapper class" file outright; fold its body into your `BaseAgentDeployer.launch()` directly (no inheritance, no hook gymnastics — just procedural code).
4. Track the source commit in your config's `upstream_version` field so consumers know what to bump and `version` property surfaces it.

Net result: the harness IS your code now. You can freely modify, simplify, drop dead branches, etc.

### 7.2 Where to write logs

The framework calls `mirror_artifacts(env, mirror)` after `launch` returns and before VM release. For native deployers it copies your `work_dir(...)` to `<run_dir>/origin_log/<config.name>/`. So your `launch()` should:

```python
async def launch(self, session, *, prompt, timeout_s):
    run_id = uuid.uuid4().hex[:12]
    self._work_dir = (
        Path(tempfile.gettempdir()) / "ale" / "<your_agent>" / f"{self._task_id}-{run_id}"
    )
    self._work_dir.mkdir(parents=True, exist_ok=True)
    # ... point your harness's session/memory dirs underneath self._work_dir ...
```

Then `work_dir(self, session) -> str | None` returns `str(self._work_dir)`. The framework handles the copy.

`task_id` (used by some harnesses as a memory keying string) isn't passed to `launch()` directly. Override `run()` to capture it from `env.task_path` before delegating to base:

```python
async def run(self, env, *, variant_index=0):
    self._task_id = (env.task_path or "default").replace("/", "__")
    return await super().run(env, variant_index=variant_index)
```

### 7.3 API keys → `os.environ` patch

Most LLM SDKs (litellm, anthropic, openai) read keys from `os.environ`. ALE convention forbids `os.environ.get(...)` reads from configs (cross-experiment leak risk), so the deployer sets them just-in-time and unwinds:

```python
@contextlib.contextmanager
def _patched_environ(self, env: dict[str, str]):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try: yield
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else:         os.environ[k] = v

# in launch():
with self._patched_environ(self._prepare_env()):
    await asyncio.wait_for(_drive(), timeout=timeout_s)
```

**Concurrency caveat**: `os.environ` is process-wide. With `concurrency > 1` and DIFFERENT keys per unit, this races. Document the caveat; same-key batches are fine. v2 fix is subprocess wrapping per unit (out of scope for first native deployer).

### 7.4 Wall-clock timeout

The agent's own `max_turns` / `max_steps` controls step count, but native agents can hang on stuck LLM calls or runaway tool execution. Wrap the run loop:

```python
try:
    await asyncio.wait_for(self._drive(), timeout=timeout_s)
except asyncio.TimeoutError:
    return AgentRunResult(status="timeout", duration_s=..., error=f"wall budget {timeout_s}s exceeded")
```

### 7.5 Status mapping

Native agents typically have richer outcome semantics than just exit_code. Map them onto ALE's three:

| Internal outcome | `AgentRunResult.status` |
|---|---|
| Agent emitted "done" signal explicitly | `completed` |
| Hit `max_steps` budget without errors | `completed` (finished, just at budget — not a failure) |
| Loop exited without "done" and not at max_steps | `failed` (suspect — should not happen) |
| `asyncio.TimeoutError` from wait_for | `timeout` |
| Any other exception | `failed`, error from `f"{type(exc).__name__}: {exc}"` |

### 7.6 Trajectory translation

For agents that write structured logs to disk (most do), put the parser in a sibling file like `transcript_to_trajectory.py` and call it from `collect()`:

```python
async def collect(self, session, run, builder):
    if not self._work_dir or not self._work_dir.exists():
        builder.add_step(source="system", message="...", extra={"reason": "no_work_dir"})
        return
    try:
        parse_transcripts_into(self._work_dir, builder)
    except Exception as exc:
        builder.add_step(source="system", message=f"parse failed: ...", extra={"reason": "parse_error"})
    builder.trajectory.extra.setdefault("<your_agent>", {}).update({...})
```

The parser emits `builder.add_step(source=..., message=..., tool_calls=..., observation=..., metrics=...)` calls. Mapping table:

| Agent log event | ALE Step source | Filled fields |
|---|---|---|
| LLM turn (assistant text + function_call(s) + thinking) | `agent` | `message`, `reasoning`, `tool_calls`, `metrics` (one Step per assistant turn — merge all blocks into one) |
| Tool result returned to agent | `environment` | `observation.results: list[ToolResult]` (link via `tool_call_id`) |
| Framework / runtime note | `system` | `message`, `extra={"reason": ...}` |

If the agent writes accurate token totals to a sidecar file (e.g. `state.json` for OpenClaw), prefer that over summing per-step transcript usage — the sidecar usually captures helper / compaction calls that bypass the transcript writer. Land the aggregated totals in `builder.trajectory.extra["<your_agent>"]["usage"]` for downstream consumers.

### 7.7 Test isolation

Unit smoke for native agents can validate the trajectory parser without ever calling the LLM. See `tests/smoke_ale_claw_transcript.py` for the pattern: hand-craft a fake transcript on disk, run your `parse_transcripts_into(...)`, assert step shape + metric aggregation. **Always doable in CI without API keys.**

End-to-end smoke against a real VM + LLM has cost; gate it on env-var presence and run manually. See `tests/integration/static_smoke_ale_claw.py`.

### 7.8 Dependency story

Native deployers usually pull in heavy LLM SDKs (`litellm`, `anthropic`, `openai`, ...) and the cua `agent` SDK. Add them to ALE's `pyproject.toml`:

```toml
dependencies = [
    "cua-bench",
    "cua-agent",        # for `from agent import ComputerAgent` etc.
    "cua-computer",     # transitive but pin to keep the chain consistent
    "cua-core",         # for `core.telemetry`
    # ...
]

[tool.uv.sources]
cua-bench    = { path = "../agenthle/submodules/cua/libs/cua-bench",   editable = true }
cua-agent    = { path = "../agenthle/submodules/cua/libs/python/agent",    editable = true }
cua-computer = { path = "../agenthle/submodules/cua/libs/python/computer", editable = true }
cua-core     = { path = "../agenthle/submodules/cua/libs/python/core",     editable = true }
```

Pin all cua-* siblings to the same submodule path (avoid PyPI drift between sibling versions). litellm + Pillow + typing-extensions usually come transitively via `cua-agent`.

---

## 8. Reviewer checklist (paste into PR description)

```
[ ] Config subclasses BaseAgentConfig; name is ClassVar; __post_init__ validates required fields
[ ] No os.environ reads in config
[ ] install is verify-or-install (skips when image-baked)
[ ] launch returns AgentRunResult on all paths; uses setsid (Linux) / Start-Process (Win)
[ ] collect maps to {user, agent, environment, system} step sources; partial logs OK
[ ] work_dir returns an absolute path under install_paths.work_dir(os, agent_name) (in-VM)
       or under a host-side run-local dir (native; work_dir_on_vm=False)
[ ] Registered in AGENT_REGISTRY (or documented to use fqdn)
[ ] Unit smoke passes (smoke_<agent>.py via StubProvider)
[ ] cli_version / version property surfaces the pinned CLI version
```
