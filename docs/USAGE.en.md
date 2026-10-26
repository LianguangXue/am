# Using it day to day

> One rule: **at the start of every agent session, say "follow your workspace
> instructions first".**

Everything below is optional once that happens, because the entry stanza in
`~/AGENTS.md` / `~/CLAUDE.md` tells the agent to read the brief itself.

---

## Language

English is the default on this machine (`LANG=en_US.UTF-8`). Chinese is one flag
away, and the choice affects the brief, the overview, `status`, `doctor`,
`recall` markers, error messages, and the opening prompt:

```bash
am --lang zh brief --for codex     # or export AM_LANG=zh
am --lang en brief --for codex     # explicit English
```

Task content is never translated — it is whatever the agent wrote. A brief can
carry English prose and Chinese decisions side by side, which is the point.

---

## Every command except `am brief` is optional

`am brief` is the only thing that has to run — it is the successor's entry point.
Everything else is an additive layer:

| What you do | What it buys |
|---|---|
| nothing | the successor still sees the last commands from the transcript |
| `am start <id>` | the work has a name and appears in the multi-task table |
| \+ `am next "..."` | the successor knows what you *intended*, not just what you ran |
| \+ `am log decision` | nobody silently reverses your reasoning |
| \+ `--accept` | someone else can judge "done" while you are away |

If you do not know what "done" means yet, skip `--accept`. The brief shows
`done when: not recorded (optional)` — that is a state, not an error.

---

## See what the sessions are doing

**No task has to exist first.** When nothing is registered, `am brief` lists the
recent sessions, three lines each:

```
### `dfc8985c` · claude-code · quiet 4m · FeatureEnhance

- Started from: can we make the static_bar quota accounting correct
- Latest ask: ok, do your recommendations
- Progress: this session hit the weekly cap; stopped at the last tool call
- Last action: `pytest -x tests/test_parity.py`
- Continue: `am adopt dfc8985c`
```

Each field answers a different question:

| Field | Source | Answers |
|---|---|---|
| Started from | the session's **first user message** | why this session exists |
| Latest ask | the last user message | where you redirected it |
| Progress | the **last assistant message** | how far it got — agents summarise on their way out |

Plus the session title that Claude Code and DSH generate themselves
(`FeatureEnhance`, `反代`), and the last command as a fallback.

All of it is verbatim from the transcript — **no model is called**.

To continue one:

```bash
am adopt <session-id>     # becomes a task, and this session takes it over
```

The table on its own: `am sessions`.

---

## The three moments

### 1. Start

```bash
am brief --for claude-code      # or --for codex / --for dsh
```

**If the brief says nothing is open** and you are in fact about to work, declare
it first:

```bash
am start <id> --accept "<how we know it is done>"
```

`am start` does two things in one step: creates the task if it does not exist,
then binds this session to it. **Do it before working, not after** — a task that
was never registered does not exist as far as any successor is concerned.

Five blocks: goal · current task with its acceptance criterion · recent events
plus machine-extracted actions · **the exact next command** · blockers and
decisions not to reverse.

If block 2 says the lease belongs to an agent that is dead or out of quota:

```bash
am claim <task-id> --force
```

### 2. While working

Log only what is worth remembering. Do **not** log a transcript — your commands
are already captured from the session files.

```bash
am log decision "why we chose this" --task <id>
am log result  "what works now" --task <id> --evidence "pytest ... → 12 passed"
```

### 3. Stopping, or the quota is about to run out

```bash
am next "<the exact command you would run next>" --task <id>
```

**This is the one that matters.** Everything else — what you touched, what
broke — is already in the transcript. Only you know what you intended next.

---

## Switching agents

Claude is out of quota, so start codex in the same directory:

```bash
cd ~/your-project
codex
> follow your workspace instructions, then continue
```

Codex runs `am brief --for codex` itself, sees the lease on `claude-code`, and
takes it over with `am claim <id> --force`. You never type a task id.

When Claude is back:

```bash
am brief --for claude-code
```

Block 3 is now what codex did, block 4 is what it left as the next step.

---

## Many sessions at once

With several sessions in flight, `am brief` prints a table instead of a single
task:

```
| id          | status  | agent       | session       | quiet   | last action      |
| feat-imb    | claimed | claude-code | fffbbe58-9ad0 | 12m     | pytest tests/... |
| mig-dl2     | claimed | claude-code | dfc8985c-4111 | **18m** | python -m mig... |
```

`quiet` is how long that **session** has been silent; bold means over 15 minutes,
i.e. probably dead. Then:

```bash
am brief --task mig-dl2      # expand one
am claim mig-dl2 --force     # take it over
```

or just say "continue the mig-dl2 one".

The store deliberately does not guess which task to resume: which one you want
depends on what you are doing right now, and no file on disk knows that.

---

## Launching

### Terminal

```bash
am resume codex --exec       # correct directory + opening prompt, one command
```

Manual equivalent: `cd ~/your-project && codex`, then paste the opening message.

### Cursor

Both extensions are installed (`anthropic.claude-code`, `openai.chatgpt`). Open a
**new** agent session and paste:

```bash
am resume codex --prompt-only
```

The extensions run with the folder you opened as cwd — `$HOME` today, which
is exactly where the entry files live.

---

## Finding things

```bash
am recall "truncation test"                  # exact, ~2s
am recall "how did we handle the quota" --smart   # semantic, ~12s
am recall "static_bar" --agent codex         # narrow to one agent
```

Both languages work as queries; the index is built from whatever the
transcripts contain.

---

## Health

```bash
am status     # task table + recent observations
am doctor     # is the store handoff-ready (exit 1 = problems)
am where      # where the store lives
```

---

## Don'ts

- **Don't hand-edit** `state.md` or `journal/*.jsonl`. One is compiled, the other
  is an audit log.
- **Never put secrets on a command line.** Transcript capture copies commands
  verbatim into `tail/`.
- Don't expect `claude --continue` / `codex resume` to work across models. They
  only resume their own sessions; cross-model continuity lives on disk.

---

## When something looks wrong

| Symptom | Check |
|---|---|
| Agent does not know about any of this | `am doctor` — does its instruction file carry the `am:entry` stanza |
| `am: no .agents/ store found` | `~/.am-root` pointer, or `cd` into the repo |
| Brief says "no open task" | `am status` — everything may genuinely be closed |
| `--smart` errors | it falls back to literal search automatically; the index is optional |
