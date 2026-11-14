# am — one memory for all your coding agents

[![smoke](https://github.com/LianguangXue/am/actions/workflows/smoke.yml/badge.svg)](https://github.com/LianguangXue/am/actions/workflows/smoke.yml)

`claude-code`, `codex` and `dsh` write to **one store on disk**. When one runs out
of quota or dies mid-task, the next picks up from the artifacts instead of from
scratch — and when the first comes back, it continues from whatever the second
finished.

No daemon, no database, no API keys. The core is a stdlib-only Python CLI plus a directory; the optional work protocol
ships in the adjacent `bin/am_work.py` module.

The 0.5 dashboard includes a dedicated **Delegate 子任务** workspace (`/#delegate`):
live status/phase, model and effort, heartbeat, observed tokens, errors and exact
parent-session links. Filter by activity, attention, provider or search text. It reads
bounded local indexes without invoking models or requiring an am task binding.
See [dashboard usage](docs/DASHBOARD.zh-CN.md). The existing memory store is preserved.
Version0.5.1 refuses to overwrite unreadable task, lease, config and handoff records;
read-only dashboard projections retain tolerant reads. See [store recovery](docs/STORE-INTEGRITY.zh-CN.md).

```
$ am brief --for codex

## 1. Goal
Ship the third value-exact pass over the six un-profiled sets.

## 2. Current task
- id: `sets3` — optimize state/latency
- lease: held by `claude-code` / `dfc8985c` for 44 more min, quiet 18m (**likely dead**)
  - take it over only if that session is dead: `am claim sets3 --force`
- **done when**: FULL GATES vs REF at 0 diff, cachegrind not slower on 10 sets

## 4. Next exact step
pytest tests/test_parity.py -k sets3
```

---

## Why this exists

Coding agents are stateful in the worst possible way: their context lives in a
process that can be killed without warning. Quota runs out, the session dies, and
the next agent starts from nothing. You re-explain; it re-reads files; sometimes
it redoes work that was already finished.

But the agents already write **JSONL transcripts**. The capture problem is
therefore free — what is missing is a protocol for turning "what happened here"
into "what should happen next".

`am` is that protocol, and nothing more. It is not a task manager and not a
second brain. It is the shortest path from "this agent died" to "another one is
working again".

---

## Four layers

| Layer | What it does | Cost |
|---|---|---|
| **Journal** | append-only events the agents declare: goal, decisions, next step | one line each |
| **Capture** | reads the three transcript formats and records what actually ran | zero integration |
| **Brief** | five blocks that let any agent resume without re-deriving | ~900 tokens |
| **Recall** | full-text search over every transcript, optionally semantic | 0.15–12 s, local |

Everything is plain files under `.agents/`, so `git log`, `grep`, `cat` and `rsync`
all work on your agent's memory.

---

## 快速开始

[中文安装与联动手册](docs/INSTALL.zh-CN.md) · [delegate 三宿主安装](https://github.com/LianguangXue/delegate/blob/main/docs/INSTALL.zh-CN.md)

## Install

```bash
git clone https://github.com/LianguangXue/am.git
cd am
./install.sh                      # links ~/.local/bin/am
```

Then, in the project the memory should cover:

```bash
cd ~/my-project
am init --project my-project --link   # creates ./.agents and ~/.am-root
```

Paste [`templates/AGENTS-entry.md`](templates/AGENTS-entry.md) into **both**
`AGENTS.md` and `CLAUDE.md` at your project root — Claude Code reads `CLAUDE.md`,
Codex reads `AGENTS.md`, and DSH reads both. Then:

```bash
am doctor                         # verifies the wiring, exits 1 on problems
```

Nothing else is required. `am` works with all three agents from day one because
they already write transcripts to disk.

---

## Quick start

```bash
am start my-task                  # create a task and bind this session to it
am log decision "why we chose this"
am next "pytest -x tests/test_flow.py"
am brief --for codex              # what a successor sees
am done my-task --evidence "12 passed"
```

Stop an agent at any point — including by running out of quota — and the next one
can continue:

```bash
am resume codex --exec            # correct cwd + opening prompt, one command
```

Everything except `am brief` is optional. If you declare nothing, the brief still
tells the successor what was running, because the transcript scan is automatic.

---

## Commands

| Command | Purpose |
|---|---|
| `am brief [--for X] [--task ID]` | the resume brief — the only command that must run |
| `am start <id>` / `am claim <id> --force` | bind this session to a task |
| `am next "<cmd>"` | the exact next step, so handoff is mechanical |
| `am log decision\|result "…" --evidence "…"` | what is worth remembering |
| `am done <id> --evidence "…"` | close a task, with proof |
| `am sessions` / `am adopt <id>` | see what recent sessions were doing, take one over |
| `am recall "<terms>" [--smart]` | search all transcripts, literal or semantic |
| `am serve` | live dashboard on `http://127.0.0.1:37778` |
| `am hide <id>` / `am prune` | suppress dead sessions, archive settled work |
| `am doctor` / `am where` / `am status` | health, store location, task list |

`--lang en|zh` switches every message, the brief template and the resume prompt.
Task content is never translated.

---

## Dashboard

`am serve` renders a two-pane view over the same store: a searchable, grouped
session index on the left, a summary or a session's detail on the right. It
polls every 2.5 s, redraws only when something changed, and never writes.

Useful because it answers the question a list of tasks cannot: *what were my
agents actually doing, and which of these is still alive?*

---

## Optional: semantic recall

Literal search needs the right words. `--smart` adds a vector index for when you
remember the idea but not the phrasing.

```bash
python3 -m venv --system-site-packages ~/.am-embed/venv
~/.am-embed/venv/bin/pip install sentence-transformers
am embed --days 30
am recall "the quota thing we fixed" --smart
```

Isolated on purpose: the encoder lives in its own venv, the model cache lives in
`~/.am-embed/hf`, and **every failure degrades to literal search** with a one-line
reason. `am` itself never imports a third-party package.

---

## What it deliberately does not do

- **No LLM in the loop.** Summaries come from the agents' own words — the opening
  request, the last assistant message, the last command. Nothing is paraphrased,
  nothing costs quota, nothing drifts.
- **No automatic agent launching.** Detecting three vendors' quota errors is
  brittle; the expensive part is rebuilding context, and that is what the brief
  solves.
- **No deletion of transcripts.** They belong to the agents. `am` archives its own
  artifacts and hides sessions from view — reversible, never destructive.

---

## Design notes

The full protocol, including the event schema, the extraction rules, and the
failure modes that shaped them, is in [`docs/DESIGN.md`](docs/DESIGN.md).
Usage guides: [`docs/USAGE.en.md`](docs/USAGE.en.md) ·
[`docs/USAGE.md`](docs/USAGE.md) (中文).

---

## 中文速览

`am` 让 Claude Code、Codex、DeepSeek 共用一套磁盘上的记忆。一个 agent 额度用完
死掉，另一个能接着干；额度恢复后，原来的还能从句号处继续。

```bash
./install.sh
cd ~/my-project && am init --project my-project --link
# 把 templates/AGENTS-entry.md 粘进 AGENTS.md 和 CLAUDE.md
am doctor
```

唯一必须跑的命令是 `am brief`，其余都是可选的增量。完整说明见
[`docs/USAGE.md`](docs/USAGE.md)。

---

## Tests

```bash
bash tests/smoke.sh            # end-to-end, against a throwaway store
python3 tests/stdlib_only.py   # the core tool must not import outside stdlib
```

`tests/smoke.sh` builds a store in a temp directory and exercises the paths that
matter: init, goal/task/decision/next, the brief's contents and its
"data not instruction" fence, `--lang zh`, forced lease takeover, dry-run prune,
and the dashboard's state endpoint and page shell. CI runs it on Ubuntu and macOS
against Python 3.10 and 3.12, and additionally runs the installed `am` from
`PATH`, because that is how agents invoke it.

## License

MIT — see [LICENSE](LICENSE).

## Optional delegate integration (0.2.0)

am remains independently usable without delegate. `am delegate import` accepts a
schema_version=1 JSON handoff on stdin, for an existing am task only. It saves a
bounded, versioned snapshot in integrations/delegate/<task>/<source>.json under a
single-writer lock. Duplicate/stale revisions do not overwrite newer state; conflicting
same revisions are rejected. Imports do not create tasks, claim leases, execute next
steps or declare completion. Imported content is untrusted context, never instructions.

`am delegate report --task ID` shows the imported snapshots; `am brief --task ID`
includes a bounded summary. delegate manages dispatch, model selection and its own
retryable outbox. am manages the task's durable goals, evidence and human/agent handoff.
No daemon or LLM is added to am. Upgrade delegate and am independently; an old am CLI
will reject import and delegate will retain its pending snapshot for retry after upgrade.

Version 0.3.0 adds delegate summary counts to task cards: running, uncollected,
awaiting review, accepted, needs-work and conflicting. Conflicting snapshots never
count as accepted. These are bounded imported summaries, not a process liveness
monitor or an automatic lease-transfer authority. Restart an existing am serve
process to load the new task-card UI.

Version 0.3.1 adds a separate read-only Delegate overview on the summary page,
including jobs not linked to an am task. It reads only a bounded task index from
`delegate_state_dir` (config), `DELEGATE_STATE_DIR`, or `~/.claude/delegate`;
no home-directory scans or automatic task binding are performed. The overview covers
the last 20 indexed tasks and at most 50 job records, cached for 15 seconds. It shows
provider/model, execution/review and archive state without prompts or result bodies.
Missing, oversized, malformed or non-regular records are reported as incomplete;
job/task/session identity must match. Empty am task cards explicitly show that no
delegate handoff has been linked. Resume remains a user request in the owning host,
not an action performed by this dashboard.

## Quota-first work protocol (0.4.0)

`am work ACTION` reads one bounded JSON object on stdin. It never invokes an LLM or
executes payload commands. The optional module `bin/am_work.py` must stay beside
`bin/am` (the normal source installation already does this).

Actions:
- `publish`: id, project, task_id, session_id, summary, evidence, files (absolute paths).
  Existing am task required. Updates require the original owner and expected_revision.
- `search`: exact project namespace + query. Up to three short lexical results;
  freshness is unchecked. `get`: project + id validates the nominated evidence.
- `watch`: id/task_id/session_id/manifest. The producer writes JSON
  `{"status":"completed","evidence":"exit code and artifacts"}` or status failed.
  `poll`: id/session_id. `am work poll --wait 86400` waits in code, with 30-second
  checks and no model polling, and can run through a host's background shell tool.
  `ack` acknowledges the stable event. It does not independently verify success or
  control the producer process. Without host notification, callers explicitly read
  the durable receipt; closed sessions are not automatically restarted.
- `stage`: id/task_id/files/evidence/requires (stage IDs). Only record after actual
  validation. Duplicate IDs are rejected and dependencies checked recursively.
  `stage-check`: id. Changed evidence means stale. Missing checkpoints are not proof
  that an external action never happened. This registry does not run workflows.
- `configure`: task_id/enabled. Questions default disabled. `ask`:
  task_id/session_id/target_session/question, optional artifact_versions. One new
  question per am task, <=2000 chars, no forwarding. Duplicates reuse the request ID.
  `inbox`: session_id. `reply`: id/session_id/reply (<=2000 chars). Re-enabling does
  not reset spent budget. Queueing does not wake or launch a model; host-native
  delivery or an explicit inbox read is required. This is a request-count budget,
  not an in-flight token cap. A crash after budget reservation may consume the slot
  without sending; fail closed rather than silently issue another request.

Nominate 1..16 regular files/manifests <=16MiB each. Large data must use producer
manifests; no recursive scans or extra LLM summarization. Project namespaces prevent
accidental mixing, not access control against another process using the same OS user.
All imported summaries/questions remain data, not authority to claim a lease, execute
commands or publish results. Existing delegate metrics support matched-task evaluation;
no token-savings estimate is inferred merely from a search hit.

Example lookup:

```sh
printf '%s\n' '{"project":"execution","query":"frozen replay"}' | am work search
```

Validate with `python3 -m unittest discover -s tests -p test_work.py -q` in addition
to the existing smoke suite. Every test uses disposable state and no inference.
