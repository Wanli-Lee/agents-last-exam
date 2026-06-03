# ALE Claw

**ALE Claw** is a computer-use agent for [ALE](https://github.com/rdi-berkeley/agents-last-exam),
built on the [OpenClaw](https://openclaw.ai/) agent architecture and the
[CUA](https://cua.ai) Computer-Use Agent SDK. It drives a test VM
(click, type, read/write files, run shell commands, browse the web) to complete
benchmark tasks, while managing its own conversation context the way a
long-horizon assistant does — canonical message history, tool-result
truncation, automatic compaction, durable memory, and subagent delegation.

It is ALE's first **native** deployer: the agent runs in-process in the ALE
host's Python interpreter (no subprocess, no container, not inside the VM). By
default it reaches the VM over **MCP bridge servers** — the same substrate ALE's
installed agents use — with a direct CUA Computer SDK session as the alternative
transport (see [VM transport](#vm-transport)). Per-turn transcripts, `state.json`,
and raw API result dumps are written to a host tempdir and mirrored back into the
run directory, then translated into an ALE `Trajectory`.

## What's inside

The agent loop is an OpenClaw reproduction adapted for CUA's `ComputerAgent`
lifecycle. The pieces that make it more than a thin tool-calling loop:

- **Canonical context pipeline** — a single typed message format with sanitize
  passes (orphaned tool-pair repair, thinking-block handling, provider-specific
  ordering) before each API call (`canonical/`).
- **Budget-aware compaction** — when the context window fills, older history is
  chunked and summarized in place and the loop continues, no agent rebuild
  (`context.py` + `compaction.py`).
- **Durable memory + pre-compaction flush** — the agent persists task memory and
  a session log to disk; a flush turn runs before compaction so nothing
  important is lost (`memory*.py`).
- **Subagent delegation** — spawn focused workers: an async general subagent
  (its own session + compaction) and a blocking GUI subagent that relays
  vision→action through a second `ComputerAgent` (`subagent/`).
- **Tool suite** — file read/write/edit, shell exec, web search/fetch, image
  analysis, milestone screenshots, and memory tools (`tools/`).
- **Multi-provider via OpenRouter** — a unified Chat-Completions loop registered
  for `openrouter/*` plus image sanitization (resize/transcode) so screenshots
  fit provider limits (`unified_loop.py`, `image_sanitization.py`).

## VM transport

ALE Claw keeps its thick `read` / `write` / `edit` / `exec` / `computer` tools,
but the I/O *underneath* them runs over one of two interchangeable transports,
chosen per concern:

| Concern | `session` (direct) | `mcp` (bridge) |
|---|---|---|
| Non-GUI I/O — `read`/`write`/`edit`/`exec` | CUA `RemoteDesktopSession` | `vm_mcp_server` bridge |
| GUI — `computer` | `session.computer` | `cua_mcp_server` bridge |

- **`substrate_transport`** (default `mcp`) picks the non-GUI transport. In `mcp`
  mode the file/shell tools route through the `vm_mcp_server` Node bridge — the
  agent consumes the same MCP substrate as ALE's installed agents — instead of
  `RemoteDesktopSession`. Tool granularity and all the value-add logic (adaptive
  paging, image sanitize, `edit` exact-match recovery, `exec`
  truncation/timeout/cwd) are unchanged; only the I/O moves.
- **`gui_transport`** (default `session`) picks the GUI transport. Set it to
  `mcp` (requires `substrate_transport=mcp`) to route the `computer` tool through
  the `cua_mcp_server` bridge; `MCPComputerHandler` converts the model's pixel
  coordinates to/from the bridge's normalized `[0,1000]` space. With both knobs
  on `mcp`, ALE Claw never touches `RemoteDesktopSession` for tool I/O.

The bridges are Node MCP servers installed on the host per episode (under
`<work_dir>/mcp/`) by the deployer and driven by a thin async client
(`harness/tools/mcp_runtime.py::MCPRuntime`). The harness consumes MCP as a
*backend* — it does not expose MCP tools to the model.

## Running it

ALE Claw runs as an ALE agent (`harness: ale_claw`). Point an agent config at it
and run an experiment:

```yaml
# configs/agents/ale_claw_or.yaml
harness: ale_claw
model: openrouter/anthropic/claude-sonnet-4.6
config:
  max_turns: 100
  substrate_transport: mcp   # non-GUI tools via the vm_mcp_server bridge (default)
  gui_transport: mcp         # computer tool via the cua_mcp_server bridge (default: session)
  thinking_level: "off"
```

```bash
export OPENROUTER_API_KEY=...
uv run python -m ale_run run experiments/my_experiment.yaml
```

For a programmatic/standalone construction, the deployer and its config are:

```python
from ale_run.agents.ale_claw import AleClawConfig, AleClawDeployer

cfg = AleClawConfig(
    model="openrouter/anthropic/claude-sonnet-4.6",
    max_turns=100,                  # OpenClaw max_steps
    thinking_level="off",           # off | low | medium | high
    disabled_tools=["web_search"],  # default; set to [] + export BRAVE_API_KEY to enable
)
```

The full kwarg surface is documented in `config.py`. A few knobs worth calling out:

- **`substrate_transport` / `gui_transport`** — which transport reaches the VM;
  see [VM transport](#vm-transport).
- **`summary_model` / `gui_model` / `lightweight_model`** — route compaction,
  GUI subagent, and helper calls through cheaper sibling models to save cost on
  long runs. Default: all use `model`.
- **`thinking_level`** (`off | low | medium | high`) — Claude reasoning depth;
  defaults per-model. Variants exist for flush / compaction / vision / GUI.

API keys are read from the environment: litellm picks up `OPENROUTER_API_KEY`
(or `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) straight from `os.environ`, so export
the key for your provider before running — the deployer errors early if none is
set. Web search additionally needs `BRAVE_API_KEY` (and `web_search` removed from
`disabled_tools`).

## Layout

```
ale_run/agents/ale_claw/
├── config.py                   — AleClawConfig (standalone dataclass)
├── deployer.py                 — AleClawDeployer (install → launch → parse_artifacts)
├── transcript_to_trajectory.py — on-disk transcripts → ALE Trajectory (ATIF) steps
├── README.md                   — this file
└── harness/                    — the OpenClaw agent, in-tree and ALE-owned
    ├── AGENTS.md               — system-prompt context file
    ├── agent_loop.py           — OpenClawComputerAgent (the run loop)
    ├── computer_handler.py     — GUI handlers: session + MCP (MCPComputerHandler)
    ├── session.py / replay.py  — session state + cross-run transcript replay
    ├── canonical/              — typed message format + sanitize passes
    ├── tools/                  — fs / shell / web tools + mcp_runtime (MCP bridge client)
    ├── subagent/               — general + GUI subagent engines
    ├── adapters/               — CUA SDK callback extensions
    └── … (context, compaction, memory, prompt, unified_loop, …)
```

## Provenance

The harness reproduces OpenClaw's agent-side architecture but is **fully
ALE-owned** — no vendored namespace, no submodule, no upstream sync. The
`upstream_version` field in `config.py` records the OpenClaw commit the design
was adapted from, for provenance only. Develop here directly; see
`harness/AGENTS.md` for the agent's own system-prompt context and the repo-root
`AGENTS.md` for the general deployer-author workflow.
