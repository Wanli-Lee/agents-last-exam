# Agent Adapter

Agents' Last Exam tasks are written as Cua-compatible desktop tasks. A benchmark
agent is expected to:

1. receive the task instruction from `cua-bench`;
2. interact with the remote desktop/session;
3. use the task's visible `input/` and `software/` surfaces;
4. write final deliverables into the task's `output/` directory.

For the default Cua solver path, configure:

```bash
export CUA_ENV_API_URL="http://YOUR_REMOTE_DESKTOP_ENDPOINT:5000"
export OPENAI_API_KEY="YOUR_OPENAI_COMPATIBLE_KEY"
```

Then run:

```bash
bash scripts/run_task.sh tasks/helloworld openai/computer-use-preview
```

Custom agents can be integrated by implementing a Cua-compatible agent entry
point and passing its registered name through `ALE_AGENT_NAME`.

```bash
export ALE_AGENT_NAME="your-agent-name"
bash scripts/run_task.sh tasks/helloworld your-model-name
```

The public skeleton does not prescribe a single model provider. OpenAI-compatible
API bases can be supplied with `OPENAI_API_BASE` when supported by the agent.
