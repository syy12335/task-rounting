# Environment-Runtime

[中文](README.md) | English

[![Tests](https://github.com/syy12335/task-rounting/actions/workflows/tests.yml/badge.svg)](https://github.com/syy12335/task-rounting/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Environment-Runtime is a lightweight Agent Runtime for engineering scenarios. As OpenClaw gains more attention in enterprise engineering workflows, a practical need becomes clearer: a general-purpose agent runtime design may not directly cover every engineering deployment pattern. This project narrows the scope to high-certainty engineering workflows and aims to make common engineering tasks easier to organize, reuse, and operate. It is still growing; issues and PRs are welcome.

It is useful when:

- Most tasks are stable engineering workflows, such as tests, evaluations, inspections, retrieval, batch jobs, or pre-release checks
- Some tasks can be handled by fixed scripts or workflows, while an agent still handles routing, clarification, summarization, and failure recovery
- You want the controller to make decisions from explicit Environment state, instead of hidden context or the full trace by default
- Long-running tasks should return `running` first, then fill results back through process-level skills / workflows

It is not a good fit when:

- Almost every request needs open-ended reasoning and there are few deterministic workflows to extract
- You only need a chatbot and do not need structured tasks, Environment state, track logs, or a training loop
- You need ready-made business task types. The built-in `functest / accutest / perftest` types are examples and should be replaced in real deployments.

## Advantages

- **Observed token cost is about 7%**: in the current business scenario samples, total token usage is about 7% of directly using OpenClaw. The gain comes from the lightweight runtime design as a whole, including explicit state views, layered routing, workflow / skill execution paths, and asynchronous result collection.
- **Better fit for async long-running tasks**: long-running tasks can return `running` first and fill results back asynchronously, while the synchronous turn only handles the part that needs an immediate response.
- **More explicit state grounding**: the controller makes decisions from an explicit Environment view, which makes routing behavior easier to inspect and reproduce.
- **More reusable engineering paths**: scripts, workflows, and skills can become fixed execution paths over time, while the agent handles routing and failure convergence.
- **Easier badcase review**: tasks, failures, retries, async collection, and final replies all leave structured traces for locating controller / executor / skill issues.

These benefits depend on task distribution. The more deterministic workflows you have, the stronger the payoff; if most requests are open-ended reasoning tasks, it behaves closer to a normal executor agent. The repository still needs a reproducible benchmark, so treat it as a mechanism validation and extension point rather than a polished benchmark claim.

---

## Core Mechanics

### 1. Environment: the single source of truth for runtime and training

`Environment` is the shared state container for the whole graph. Multi-turn tasks, async result collection, failure retries, history summaries, and final replies are all organized around it. The controller does not read scattered context directly; it reads a formal view derived from the Environment.

The training side reuses the same entry point: `build_controller_state_input(...)` turns the runtime Environment into `{ USER_INPUT, ENVIRONMENT_JSON, SKILLS_INDEX }`. This keeps training samples and online controller inference aligned on the same state shape, reducing drift between training-time context and runtime context.

### 2. Layered routing: choose the execution layer by uncertainty

Many general agentic frameworks are designed to preserve flexibility for open-ended scenarios. In narrower engineering workflows, however, some tasks follow relatively fixed execution paths. This README uses testing-related task types as examples only to explain the routing layers; the framework is not limited to testing scenarios.

Environment-Runtime splits tasks into multiple execution layers by certainty. The more deterministic the task is, the earlier it can move into a stable workflow / skill path. The controller only handles routing and structured task generation, with `max_steps=3` by default. Only remaining high-uncertainty tasks enter the full executor loop, with `max_steps=4` by default.

```text
User input
    |
    v
+---------------------------------------------------------+
| Controller Agent   (LLM, max_steps=3, strict schema)    |
| Identifies task type and emits a structured Task         |
+--------------+------------------------------+-----------+
               |                              |
    +----------v----------+         +---------v----------+
    | functest /          |         |      executor      |
    | accutest / perftest |         |   flexible tasks   |
    +----------+----------+         +---------+----------+
               |                              |
    +----------v----------+     +-------------+--------------+
    | ThreadPoolExecutor  |     |             |              |
    | async dispatch      |     | no skill    | sync skill   | pyskill
    | returns running     |     | free-form   | script sync  | subprocess
    | without blocking    |     | flexible    | blocking     | non-blocking
    +---------------------+     +----------------------------+
```

The `functest / accutest / perftest` nodes are built-in placeholder task families used to demonstrate layered routing for high-certainty tasks. In a real deployment, they should be replaced with your own business task types.

The practical intuition is simple: the more retries and IO-heavy context each run brings in, the more execution-layer choice matters. Tasks that can be stabilized as workflows can use more deterministic paths, while the full agentic loop remains available for requests that need more flexibility.

Additional LLM involvement after controller routing:

| Execution layer | Additional LLM involvement | Notes |
|-----------------|----------------------------|-------|
| Built-in example task types (`functest / accutest / perftest`) | Very low | After controller routing, dispatches directly to `ThreadPoolExecutor`; execution does not enter the executor loop |
| pyskill (`skill-mode=pyskill`) | Minimal | The LLM only decides whether to start the skill; execution runs asynchronously in a subprocess |
| sync skill (`skill-mode=sync`) | Low | The LLM selects the skill, then a script performs the execution |
| flexible executor | Full | Enters the full executor agentic loop (`max_steps=4` by default), for higher-uncertainty requests |

### 3. PySkill: process-level non-blocking execution and idempotent result collection

For fixed but long-running skills, declare `skill-mode: pyskill`. When the executor selects the skill, it dispatches it through `subprocess.Popen` without blocking. The source task immediately becomes `running`, and `track` records `run_id / pid / dispatch_pyskill`.

Process management details:

- Each pyskill process has a unique `run_id`; stdout and stderr are written under the skill directory's `.pyskill_runtime/`
- `collect_workflows` and `pre_reply_collect` can both collect results, but the same `run_id` is filled back only once
- `pre_reply_collect` checks dead processes, timed-out tasks, and lost handles before every reply, then converges them to `failed`
- When a result is collected, the graph creates a `pyskill_task` and links the source task's `result` back to `pyskill_task(round_id=..., task_id=...)`

### 4. Controller post-training: data feedback loop

Controller post-training is built around the same Environment state protocol. It forms one continuous feedback loop from base protocol samples, on-policy rollouts, and badcase filtering to preference optimization:

```text
manual_protocol_v1 -> SFT warm start -> GRPO -> holdout evaluate -> teacher_queue / annotate_queue -> preference_admissions -> DPO -> next GRPO ...
```

SFT first pulls the controller into a stable protocol input/output space. GRPO samples candidate actions from the current policy and exposes the real error distribution. When the teacher accepts a badcase, it creates a same-state gold case; the gold output and the current policy bad output become a `chosen / rejected` preference pair, enter `preference_admissions`, and are then consumed by DPO to keep improving the controller before the next GRPO round.

The controller post-training reward is not only about whether the output looks like the gold action. It gives the highest weight to whether the decision is grounded in the visible state:

```text
environment = 0.5
action      = 0.3
args        = 0.2
```

The `environment` dimension checks whether the candidate is grounded in the currently visible state. The reward teacher may only use `USER_INPUT + ENVIRONMENT_JSON + SKILLS_INDEX`; it does not use hidden state, verifier sidecars, or the full trace unless that trace is explicitly visible. This puts the main training pressure on avoiding invented invisible facts and not ignoring explicit Environment state.

### 5. Track: observable logs and a low-coupling state channel

`TaskRecord.track` is the shared execution trace across controller, executor, pyskill, diagnoser, and reply. `update_node` merges controller trace and agent track into the Environment; failure diagnosis and final reply continue appending structured events to the latest task.

Track is not exposed to the controller by default. It is only included through explicit reads such as `include_trace=true` or `previous_failed_track`, which prevents large trace payloads from polluting normal routing.

Track also acts as lightweight state sharing. `_build_round_skill_read_context(...)` scans `read SKILL.md` events already recorded in the current round, so later executor steps know which skill files have already been read and avoid duplicate reads in the same round.

### 6. Context compression: three layers of defense

Context control has three layers:

1. Agent Memory private compression: each agent maintains its own memory and summarizes it after `context_window_tokens` is exceeded.
2. Tool result trimming: oversized tool results are trimmed with a `head + mid_hits + tail` strategy.
3. Environment History Rollup: old rounds are folded into `history_summaries` and `history_meta_summary`.

Rollup does not blindly compress all history. Rounds related to `running` tasks, recent failures, and source / pyskill links are protected so collection, retry, and traceability are not lost after compression.

## Quick Start

```bash
python -m pip install -e ".[dev]"

# Optional: controller post-training dependencies
# for SFT / GRPO / DPO. CUDA environments must match verl + SGLang.
# pip install -r requirements-post-training.txt

# Default: Alibaba Cloud Model Studio / Bailian
export MODEL_PROVIDER=aliyun
export EMBEDDING_PROVIDER=aliyun
export API_KEY_Qwen=<your_key>

# Optional: use local SGLang
# export SGLANG_MODEL_PATH=path/to/Qwen3-4B
# export SGLANG_SERVED_MODEL_NAME=qwen3-4b
# export SGLANG_API_KEY=EMPTY
# ./scripts/sglang/start.sh
# ./scripts/sglang/status.sh
# export MODEL_PROVIDER=sglang
# export EMBEDDING_PROVIDER=aliyun
# If local SGLang also serves embeddings, use:
# export EMBEDDING_PROVIDER=sglang
# To stop the local service:
# ./scripts/sglang/stop.sh

# Interactive mode: reuse one environment across turns
python scripts/run/run_cli.py --config configs/graph.yaml --interactive

# Optional: single input
# python scripts/run/run_cli.py --config configs/graph.yaml --input "Run a functional test for me"
```

After installation, shorthand console commands are also available: `environment-runtime`, `environment-runtime-show`, `environment-runtime-case`, and `environment-runtime-cases`.

The main config file is `configs/graph.yaml`. Common runtime settings are documented directly in the file, including:

- `model` / `embedding`
- `paths`
- `runtime`

More entry points:

```bash
# Print the full trace, including show_environment
python scripts/run/run_cli_show.py --config configs/graph.yaml --input "Run a functional test for me"

# Run one case with your own case.json
python scripts/run/run_case.py --config configs/graph.yaml --case path/to/case.json

# Run a directory of case json files
python scripts/run/run_cases.py --config configs/graph.yaml --cases-dir path/to/cases_dir
```

Run outputs are written by default to `var/runs/run_YYYYMMDD_HHMMSS/environment.json`.

When inspecting the execution path, start with `track`:

- If you see `agent=pyskill, event=dispatch_pyskill`, the task has entered async workflow / pyskill dispatch
- If the current round directly produces `done/failed` without `dispatch_pyskill`, it usually completed through a sync skill or executor path

## Development and Tests

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

GitHub Actions currently runs the base pytest suite on push and pull request. Post-training dependencies are not installed by default; install `requirements-post-training.txt` only when running SFT / GRPO / DPO, and make sure CUDA, verl, and SGLang match your environment.

## Limitations

- Token savings depend on the distribution of deterministic tasks. The more often the controller can intercept high-certainty tasks, the larger the savings. If most tasks fall through to the executor, the benefit naturally becomes smaller.
- pyskill / sync skill require manual maintenance. More deterministic scenarios also mean more scripts and workflow logic to maintain.
- The evaluation set is still small. Current evaluation depends on the `holdout` split under `src/task_router_graph_train/assets/manual_protocol_v1/`, which is suitable for mechanism validation but not a full production distribution.
- Business adoption still requires customization. The built-in `functest / accutest / perftest` task types are placeholders; migrating to another domain requires redefining task types, skills, and failure-handling policies.

## Documentation

- `docs/design.md`: node responsibilities, execution flow, and branch rules
- `docs/skills.md`: skill directory convention and metadata injection
- `docs/skills_runtime.md`: skill loading validation and `skill_tool` contract
- `docs/pyskill.md`: pyskill dispatch / collect / link mechanism
- `docs/agent_memory.md`: memory compression and Environment view trimming
- `docs/environment.md`: Environment data structure and task / track semantics
- `docs/track.md`: track write path, trace exposure policy, and cross-agent state sharing
- `src/task_router_graph_train/README.md`: environment-grounded controller post-training loop
- `src/task_router_graph_train/docs/grpo_dpo_loop_v1.md`: next-stage GRPO / DPO plan for the controller
- `docs/data_format.md`: input/output and sample formats
