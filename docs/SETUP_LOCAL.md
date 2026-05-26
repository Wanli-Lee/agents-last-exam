# Setup — Local (TODO)

> **Status: partially supported.** No `local` provider exists today
> (see [`ale_run/environments/providers/`](../ale_run/environments/providers/)),
> so there's no provider-managed "boot the host as a sandbox" path. **However**,
> the `LocalExecutor` is implemented
> ([`ale_run/executors/local.py`](../ale_run/executors/local.py)) — the
> `ale_claw` agent already runs in the host Python process and drives a
> remote VM via cua RPC. See the interim recipe below.

Local execution is intended for two distinct things:

1. **Local agent, remote VM** — the agent runs as a host process (no
   container, no VM) and drives a sandbox over cua RPC. **Supported
   today** via the `ale_claw` deployer.
2. **Local agent, local sandbox** — the entire run happens on the host
   (no VM at all), against the user's actual filesystem. **TODO** —
   requires a `LocalProvider` that wraps the host as a `SandboxHandle`.

---

## 1. Supported today — host-side agent + remote VM

`ale_claw` is an in-tree OpenClaw harness that runs in the framework's
own Python process and talks to a VM through `session.computer.*` RPC
calls. Use it when you want zero per-run boot cost on the agent side
while still using a real sandbox VM.

```yaml
# my_local_agent_exp.yaml
name: local_agent_demo

agent:
  harness: ale_claw
  model: anthropic/claude-sonnet-4-6
  profile: configs/agents/ale_claw_local.yaml

environment:
  provider: static                                 # or gcloud
  config:
    endpoint: http://<your-vm>:5000
    image: ale-ubuntu22

tasks: selected_tasks/helloworld.txt
```

See [`configs/agents/ale_claw_local.yaml`](../configs/agents/ale_claw_local.yaml)
for the supported config knobs (`max_turns`, `timeout_s`,
`disabled_tools`, `thinking_level`, `summary_model`, `lightweight_model`,
`image_retention_mode`).

API keys for `ale_claw` come from your shell env (or `secret/.env`):
either `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY`. Optional
`BRAVE_API_KEY` enables the (default-disabled) `web_search` tool.

---

## 2. TODO — host-as-sandbox (`LocalProvider`)

To run a task that operates directly on the host filesystem (no VM,
no docker), the framework needs a `LocalProvider` that:

- Returns a `SandboxHandle` whose `endpoint` points at a `cua-server`
  that the user runs on the host (or a no-RPC shortcut that resolves
  to direct in-process filesystem calls).
- Populates `work_dir_base`, `task_data_root`, `node`, `python`,
  `mcp_server_dir` from host paths.
- `release()` cleans up the per-run scratch dir without deleting host
  state.

Until that lands, **the safest local-on-host path is to bring up
`cua-server` yourself on the host and use the `static` provider** with
`endpoint: http://127.0.0.1:5000`. This is not officially supported but
will exercise most of the surface.

---

## TODO

- [ ] `LocalProvider` implementation + `configs/environments/local_default.yaml`.
- [ ] Decide whether host-as-sandbox should require running `cua-server`
      locally or whether an in-process shortcut is worth the
      complexity (the latter would skip HTTP overhead but bypass the
      `SandboxHandle` I/O surface — tasks that assume async RPC
      behavior might break).
- [ ] Document supported task subset for the local path — some Windows
      tasks have GUI requirements that won't work in headless local mode.
- [ ] Wire `claude_code` to support `executor: local` (currently
      `supported_executors = frozenset({"sandbox"})`, see
      [`ale_run/agents/claude_code/deployer.py`](../ale_run/agents/claude_code/deployer.py)).

Contributions welcome — file an issue first to align on the host-as-sandbox
shape.
