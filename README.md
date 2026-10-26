# am — one memory for all your coding agents

`claude-code`, `codex` and `dsh` write to **one store on disk**. When one runs out
of quota or dies mid-task, the next picks up from the artifacts instead of from
scratch — and when the first comes back, it continues from whatever the second
finished.

No daemon, no database, no API keys. The core is a single stdlib-only Python
file plus a directory.

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

## License

MIT — see [LICENSE](LICENSE).
