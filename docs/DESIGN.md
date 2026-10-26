# `~/.agents/` — shared agent memory

Cross-agent task state for **claude-code**, **codex**, and **dsh**.

The point is not to share context — that is impossible. The point is that when
one agent dies (quota, crash, timeout), the next one can resume from disk with
no re-derivation, and when the first agent comes back it can continue from
whatever the second one finished.

---

## Why this shape

Four constraints drove every decision here.

1. **Quota exhaustion is an unannounced hard kill.** The dying agent writes no
   epilogue. So state must be persisted *before* it is needed, never at session
   end. This store is write-ahead: every mutating command appends to the
   journal and recompiles `state.md` immediately.

2. **All three agents already write JSONL transcripts**
   (`~/.claude/projects/*.jsonl`, `~/.codex/sessions/**/rollout-*.jsonl`,
   `~/.dsh/sessions/*/session*.jsonl.zstd`). Capture can therefore be
   zero-integration later; nothing in this store requires a plugin.

3. **The plugin runtimes are mutually incompatible.** One plugin per agent means
   three codebases that drift. So the interface is a CLI driven through `bash`,
   which every agent has, including agents that do not exist yet.

4. **Two agents can be alive at once.** A single shared markdown file would be
   clobbered or conflict. Hence one append-only journal file *per agent per day*,
   and a `state.md` that is always a pure function of the journal.

---

## Layout

```
~/.agents/
  bin/am                        the CLI (stdlib-only python3, no install)
  config.json                   project name, lease TTL, brief budget
  tasks/<id>.json               one record per task
  journal/<agent>-<YYYYMMDD>.jsonl   append-only events; never edit by hand
  tail/<agent>.jsonl            machine observations scraped from transcripts
  .watch.json                   incremental scan cursors
  leases/<id>.json              current owner + expiry
  state.md                      COMPILED from the journal — never hand-edit
  briefs/<ts>-<agent>.md        snapshots from `am brief --save` / `am handoff`
```

`journal/` holds what agents *declared*. `tail/` holds what they *did*, extracted
from transcripts by the agent itself. Keeping them apart means a curated
decision is never buried under a thousand `cd ...` lines.

Store resolution when the CLI runs: `--root` → `$AM_ROOT` → walk upward from the
cwd for a `~/.agents/config.json`. So any command works from any subdirectory of
the repo.

---

## Event schema

One JSON object per line.

```jsonc
{"ts":"2026-10-25T22:10:03+08:00","agent":"claude-code","type":"decision",
 "task":"imb-port","summary":"必须用 FakeTs，用 Ts 会让截断测试假通过",
 "refs":["SequentialFeature/book_imbalance.py:120"],
 "evidence":"pytest tests/test_causal.py -k imb → 130 passed",
 "commit":"a1b2c3d","session":"f1613232"}
```

| field | required | meaning |
|---|---|---|
| `ts` | yes | local ISO 8601 with offset |
| `agent` | yes | `claude-code` / `codex` / `dsh` / anything |
| `type` | yes | one of the types below |
| `summary` | yes | one sentence; for `next`, the exact command to run |
| `task` | no | task id, or null for project-level events |
| `refs` | no | `path:line` pointers |
| `evidence` | no | the proof a claim is true (test output, commit, count) |
| `commit` | no | git sha |
| `session` | no | agent runtime session id, for transcript cross-reference |

**Event types**

| type | use it for |
|---|---|
| `goal` | the objective. Exactly one live; the newest wins |
| `task` | a task was created or changed |
| `claim` | a task was claimed or released |
| `decision` | a choice that a successor must not silently reverse |
| `cmd` | a command was run (noisy — briefs filter these out) |
| `result` | something now demonstrably works, with `--evidence` |
| `blocker` | work stopped for a reason a human must resolve |
| `next` | **the exact next command**, so handoff is mechanical |
| `done` | task closed, with `--evidence` |
| `note` | anything else |

`next` and `decision` earn their keep. Without them the successor re-derives the
plan from scratch, which is exactly the cost this store exists to remove.

---

## Commands

```bash
am init --project <name>                  # once per repo
am goal "…"                               # objective
am task add <id> --title "…" --accept "…" # acceptance criterion is mandatory
am task list
am start <id> [--accept "…"] [--title "…"]  # create if missing, then bind this session
am claim <id> [--ttl 45] [--force]        # TTL lease; --force to steal a dead one
am release <id> [--force]
am next "<exact command>" [--task id]     # record the next step
am log <type> "<summary>" [--task id] [--ref path:line] [--evidence "…"] [--commit sha]
am done <id> --evidence "…" [--commit sha]
am block <id> --reason "…"
am brief [--for codex] [--budget 800] [--save] [--no-scan]
am handoff --to codex                     # brief + save + warn about live leases
am watch [--once] [--interval 30] [--days 3] [--max-sessions 24] [--all]
am recall "<terms>" [--days 30] [--limit 20] [--agent codex] [--all] [--smart]
am embed [--days 30] [--all] [--model ...]   # optional vector index
am status [--no-scan]                     # human summary
am compile                                # rewrite state.md from the journal
am doctor                                 # is this store handoff-ready?
```

`--agent` overrides identity detection. Detection order: `$AM_AGENT` →
`$DSH_SESSION_ID` → `$CLAUDECODE` → any `$CODEX_*` → `unknown`.

Exit codes: `0` ok, `1` doctor found errors, `2` usage or unknown task.

---

## The resume brief

`am brief` is the only thing a resuming agent needs to read. It is generated,
never hand-written, and capped by `brief_tokens` in `config.json` (default 800).

Five blocks, all mandatory:

1. **Goal** — one sentence.
2. **Current task** — id, status, lease holder, *how we know it is done*, and
   the steal instruction when the lease belongs to someone else.
3. **Recent events** — last 8 non-`cmd` events with evidence attached, then the
   last 6 transcript observations under the heading *"actions, not conclusions"*.
   When observations exist past the newest journal event, the block says so:
   *"the previous agent very likely died mid-work"*. It fires only when that
   activity is **foreign** (an agent other than the one running the command) or
   when the gap exceeds 120 s, so an agent does not flag itself for the two
   seconds between its own last command and its journal write.
4. **Next exact step** — a copy-pasteable command, not a description.
5. **Open questions and off-limits** — blockers plus the last 3 decisions.

Section 2 never says "nothing to do" just because a lease is live. A live lease
on a dead agent is the exact situation the store exists for, so the successor is
told to `--force` instead of being told to go away.

Section 3's gap between declared events and observed actions is the single most
informative signal in the brief: it is the difference between "the agent said it
was going to do X" and "the agent did X and then the line went dead".

---

## Language

**English is canonical.** Every template and CLI message is authored in English
first, because handoffs routinely involve English tasks and this machine's locale
is `en_US`. Chinese is a translation layer over the same keys.

```bash
am --lang zh brief --for codex    # or export AM_LANG=zh
```

Resolution order: `--lang` → `$AM_LANG` → `$LANG` (`zh_*` selects Chinese,
anything else English). It switches the brief, the overview, `status`, `doctor`,
`recall` markers, confirmations, errors, and the `resume` opening prompt.

Two deliberate limits:

- **Task content is never translated.** The goal, decisions and next-step
  commands are whatever the agent wrote. A brief legitimately mixes languages —
  English prose beside Chinese decisions is the normal case here, not a bug.
- **Diagnostic strings inside `doctor` remain English.** They are single-sentence
  technical findings; translating them would double the maintenance surface for
  no reader benefit.

The implementation keeps renderers building English, and looks each message up
through `T(key, **fields)` against a `MSG` table holding `en` and `zh`. That
keeps one source of truth per string instead of two parallel code paths that can
drift.

---

## Wiring the three agents

All three read the same project-level `AGENTS.md` / `CLAUDE.md` chain, so one
stanza covers all of them:

| agent | reads | how the stanza reaches it |
|---|---|---|
| claude-code | `CLAUDE.md` at project root, `~/.claude/CLAUDE.md` global | project `CLAUDE.md` |
| codex | `AGENTS.md` at project root, `~/.codex/AGENTS.md` global | project `AGENTS.md` |
| dsh | `AGENTS.md` **and** `CLAUDE.md`, root marker `.git`, `$DSH_AGENTS_HOME` | both; identical text is de-duplicated |

The stanza lives between `<!-- am:entry -->` and `<!-- /am:entry -->`. `am
doctor` warns when either file is missing it.

Most projects have `.git` at their root, so project-root discovery stops
there. If yours does not (for example a workspace that only contains subrepos),
discovery climbs past it and your shell's `AGENTS.md` joins the global chain —
harmless, but worth knowing when a stanza seems to load twice.

---

## Capture: reading the transcripts (P1)

All three agents already write JSONL transcripts. That is the one piece of
infrastructure nobody had to build, so capture needs no hook, no plugin, and no
cooperation from an agent that is being killed.

| agent | path | pattern |
|---|---|---|
| claude-code | `~/.claude/projects/<cwd-slug>/` | `**/*.jsonl` |
| codex | `~/.codex/sessions/<Y>/<M>/<D>/` | `**/rollout-*.jsonl` |
| dsh | `~/.dsh/sessions/<cwd-slug>/<session>/` | `**/session*.jsonl.zstd` |

Per format, only the calls worth knowing about are extracted:

| agent | record | becomes |
|---|---|---|
| claude-code | `type:assistant` → `message.content[]` block `tool_use`, `name: Bash` | `cmd` with `input.command` |
| claude-code | same, `name: Write/Edit/MultiEdit` | `file` with `input.file_path` |
| codex | `type:response_item`, `payload.type:custom_tool_call`, `name: exec` | `cmd`, by extracting the JSON argument of every `tools.exec_command(...)` inside the JS wrapper |
| dsh | `type:tool/call`, `data.name ∈ {bash, pwsh, terminal, …}` | `cmd` from `data.arguments.command` |
| dsh | `type:tool/call`, `data.name ∈ {write, edit, str_replace_editor}` | `file` |

Codex needs a small balanced-brace scanner rather than a regex, because the
`exec` tool wraps the command in JavaScript (`const r = await
tools.exec_command({"cmd": "..."}); text(r.output)`) and the command itself
routinely contains braces.

**Incremental, and bounded.** Plain JSONL is read from a byte offset; a
half-written trailing line is left for the next pass. The zstd session logs have
no seekable frame boundary, so they are re-decompressed and deduplicated on
their monotonic `seq`. Scans are limited by modification time (`--days`, default
3) and by the newest N files per agent (`--max-sessions`, default 24).

**No daemon.** `brief`, `status` and `handoff` run an incremental scan before
rendering. That is the whole point: the capture has to have happened *before*
you needed it, and the only moment you reliably control is the one where you ask
for the brief. `am watch --interval 30` exists for people who want the journal
warm, but nothing depends on it.

**Scope.** A session is in scope when its recorded cwd and the store root sit on
the same path in either direction — the session ran inside the project, or in a
parent directory that contains it. A path-slug test alone is not enough and was
actively wrong here: Claude Code and DSH encode the cwd in their directory names,
but Codex partitions by date, and every agent on this machine is launched from
`$HOME`, so slug matching hid 916 Claude transcripts and all 6 Codex
rollouts. The cwd is read from the record itself (`session_meta.payload.cwd` for
Codex, the first `cwd` field otherwise) and cached per process.

`--all` disables the filter entirely.

---

## Recall: searching history instead of summarising it

`am recall "<terms>"` streams the transcripts and prints the newest matching
lines, across all three agents. Measured: **1.9 s** for a Chinese query over the
newest 60 sessions (1.5 GB of transcripts); ASCII terms cost more because every
line has to be case-folded first.

**No index, no embeddings, no LLM.** Three reasons this beats a distilled
"memory" store:

1. **Lossless.** A summary is a lossy, unreproducible paraphrase. The
   transcript is the conversation itself, so a query can find what the summary
   threw away.
2. **No tokenisation cliff.** These sessions are mostly Chinese. FTS5's default
   `unicode61` tokeniser treats a whole CJK run as one token, so `截断测试` would
   never match `…并通过截断测试` — plain byte substring matching has no such
   failure mode. In-memory trigram indexing would work but buys nothing at this
   data size; the scan is already sub-second.
3. **Nothing to maintain.** No cron, no re-index, no schema migration, no
   daemon. Deleting the store and re-running `am init` loses only the journal,
   never the recall corpus, because the corpus is the transcripts.

Cost is linear in transcript bytes, so it will degrade eventually. When it does,
add an index — but measure first: at 1.5 GB of transcripts a query is ~2 s,
because only the newest `--max-sessions` files are actually read.

### The optional semantic layer

Literal search has one real failure mode: a query that is *conceptually* right
but *lexically* absent. Asking "额度用完了怎么换另一个模型继续" matches nothing,
because the transcripts say "quota exhausted" and "hand over".

`am recall --smart` closes that gap by adding a vector index on top of the same
scan. It is strictly additive — the literal pass still runs, and any hit the
vectors miss is still shown.

```bash
am embed --days 30          # build/refresh ~/.agents/idx (one-time, minutes)
am recall "你说的那句话" --smart
```

**Isolation is the design constraint.** `am` itself stays stdlib-only; the
encoder lives in its own interpreter and its own venv:

| piece | where |
|---|---|
| interpreter | `$AM_EMBED_PYTHON`, else `~/.am-embed/venv/bin/python`, else `sys.executable` |
| dependencies | `sentence-transformers` in that venv only, created with `--system-site-packages` so it reuses the existing CPU torch instead of installing one |
| model cache | `~/.am-embed/hf` (set via `HF_HOME`), never the shared HuggingFace cache |
| model | `BAAI/bge-small-zh-v1.5` — 512 dims, ~95 MB, Chinese-first; override with `--model` or `$AM_EMBED_MODEL` |
| index | `~/.agents/idx/{chunks.jsonl, vectors.npy, meta.json}` |

**Every failure degrades to literal search**, with a one-line reason on stderr:
no venv, no model, no index, stale index, encoder crash. `am recall` on a fresh
clone with nothing installed behaves exactly as before this layer existed.

Cost, measured on this machine: ~12 s to index 500 chunks once the model is
cached, and ~8 s per `--smart` query — almost all of it is loading torch and the
model in a cold process, not the search itself. That is the price of not running
a daemon; if it becomes annoying, a long-lived embedder process is the fix.

`am embed` rebuilds the whole window each time rather than updating in place.
That is a deliberate simplification: incremental vector updates need chunk
identity across edits, and a full rebuild of a 30-day window is a few minutes.

**Measured on this machine** (12 576 chunks, 30 days, all three agents):

| | |
|---|---|
| index build | 71 s (threaded CPU), 33 MB on disk, `~/.agents/idx` |
| `--smart` query | ~12 s wall — of which 6.3 s is `import sentence_transformers` and 1.9 s the model load |
| plain `recall` | 1.9 s Chinese / 3.7 s ASCII |

Because the encoder load dominates, `--smart` prints the literal hits **first**
and the semantic pass after. Waiting 12 s for a globally-ranked merge when exact
matches are already in hand is the wrong trade; the loss is only that the two
result sets are ordered separately rather than interleaved.

`--min-score` (default 0.50) drops weak neighbours, but a fixed cosine floor is
a blunt instrument: bge-small-zh puts genuinely unrelated Chinese prose around
0.3–0.45 and related text above ~0.55, and an unusually phrased query can sit
below the floor while still being the best thing in the corpus. So when the floor
empties the list, the closest few are shown anyway and marked `weak`. Returning
nothing is never better than returning labelled weak candidates.

Two bugs surfaced while building this, both worth remembering:

- **Identity is not a filter.** `main()` overwrites `args.agent` with the
  detected agent so events get attributed correctly; `recall --agent` was reading
  the same field, so every plain `am recall` was silently restricted to the agent
  that happened to be running. The filter now has its own `agent_filter` field.
- **A scope test that looks right can match nothing.** See *Scope* above: the
  slug test excluded 916 Claude transcripts and every Codex rollout, because all
  agents here are launched from `$HOME` rather than from the repo.

---

## Many sessions at once (the normal case)

One agent routinely has several sessions in flight at once — a feature
enhancement, a migration, an investigation — all reporting the same agent name.
A lease keyed only by agent name cannot tell them apart, so it is keyed by
**session**, and a task's liveness comes from that session's own transcript.

**Session identity.** DSH exports `DSH_SESSION_ID`. Claude Code and Codex export
nothing, so `am` infers it: the session running the command wrote its transcript
seconds ago, so the newest file for that agent inside a 180 s window is almost
always it. `--session <id>` overrides the inference, and inferred leases are
tagged `session_source: "inferred"` so a wrong guess is visible.

**Liveness.** `read_lease` stats the owning session's transcript and reports
`last_seen_min`; over 15 minutes of silence marks the lease `idle`. An agent
being alive somewhere no longer implies that every one of its tasks is still
moving — which is exactly the distinction five parallel Claude sessions need.

**Choosing.** With more than one task in flight, `am brief` prints an overview
rather than a single task:

```
| id          | status  | agent       | session       | quiet   | last action      |
| feat-imb    | claimed | claude-code | fffbbe58-9ad0 | 12m     | pytest tests/... |
| mig-dl2     | claimed | claude-code | dfc8985c-4111 | **18m** | python -m mig... |
```

`quiet` is minutes since that session last wrote its transcript, and bold means
it has been silent for over 15 minutes. **The store does not guess which task to
resume.** Showing every candidate with its owner and its silence makes the choice
one glance; `am brief --task <id>` expands one. With exactly one task in flight
the full five-block brief is printed directly, so the single-task flow is
unchanged.

Claiming a task held by a *different session of the same agent* is refused by
default, and the error names the holder session and how long it has been quiet:

```
am: task 'feat-imb' is held by claude-code / fffbbe58-9ad0-4828-8bdd-0ace79775d4e,
    last active 12m ago for 44 more min;
  take it over only if that session is dead: am claim feat-imb --force
```

---

## Session digest — the extraction standard

`am brief` and `am sessions` describe each session with five fields. Each answers
exactly one question, and each is **verbatim from the transcript** — no model is
called, so nothing is paraphrased and nothing costs quota.

| Field | Source | Question it answers |
|---|---|---|
| `title` | `custom-title` (Claude Code) / `session/title` (DSH) | what the session is called, in the agent's own words |
| `intent` | first real user message | why it was started |
| `asked` | last real user message / `last-prompt` | where it was redirected |
| `progress` | last assistant message ≥ 60 chars | how far it got |
| `action` | last tool call in the transcript | what it was doing at the end |

### Why these five

A single field cannot describe a session. The opening request says why it exists;
the *last* user message says what it became; the last assistant message says what
was actually achieved — agents habitually close a turn by stating what they
finished, often with the verification output. Taking only the first message was
the original mistake: for a session that ran for hours it describes a question
nobody is asking any more.

### Read backwards, not from a fixed window

A 149 MB session (`dfc8985c`, "FeatureEnhance") keeps its last real narration
megabytes away from EOF, because quota errors and request blobs accumulate after
it. Any fixed tail window either misses the narration or reads far more than
needed. `iter_lines_reversed` walks the file from the end in 256 KB blocks and
stops at the first line that matters. zstd session logs are decompressed and
walked in memory instead, because a compressed stream has no byte-addressable
line order. Measured: 1.1 s for three sessions including that 149 MB file.

### Precision rules

- **Length floor of 60 characters** for `progress`: shorter assistant messages
  are interjections ("Let me check."), not statements of state.
- **Noise markers** dropped: `You've hit your`, `API Error`, `rate limit`,
  `context low`. These are assistant text but carry no progress.
- **Injected scaffolding** dropped from user messages: harness time context,
  `# AGENTS.md instructions`, compaction summaries, background-task completion
  notices (they arrive as `type: user` with `origin`/`turnOrigin`/`toolUseResult`
  set on Claude, and as role `user` on Codex).
- **Head *and* tail** are kept when truncating a long progress message: the state
  ("currently being reviewed: X") sits at the end while the framing sits at the
  start, so a head-only clip discards the half that matters.
- **Markdown is stripped** so a paragraph of `##`/`**`/table pipes does not turn
  into unreadable noise on one line.

### Workflow-driven sessions

A session that drove a Claude Code **Workflow** records almost nothing useful in
its transcript: the orchestrator only narrates "round 3 is still running". The
authoritative record is the run file at
``<session-dir>/<session-id>/workflows/wf_<run>.json``, and it carries the whole
answer:

| field | meaning |
|---|---|
| `workflowName` / `status` / `error` | what it was, and why it stopped |
| `phases` | the declared phases (Baseline → Plan → Implement → Integrate → Release prep) |
| `workflowProgress[]` | one entry per agent, with `phaseIndex` and `state` |
| `logs` | the verdict stream |
| file mtime | when it last made progress |

The `logs` grammar is small and stable: ``area: ACCEPT``, ``area: REJECT``,
``area: no verdict``, and ``[impl:area] failed: <reason>``. Parsing four regexes
against it yields the accepted list, the rejected list, the areas that never
finished, and the reason each one died.

Two things this catches that nothing else does:

- **Why it stopped.** `status: failed` with ``AGENT_DIED: X — resume this run``
  plus ``[impl:X] failed: You've hit your weekly limit`` names the exact agent and
  the exact cause.
- **That it is dead at all.** The run file's mtime said 3 days ago while the
  watchdog's own `state.json` still claimed `"running"`. Staleness has to be
  measured from file activity, never from a status field somebody wrote earlier.

**Resume pointers.** The journal's `result` entries also carry `worktrees` and
`commits` per area, which is what lets a *different* agent pick the work up:
`wf6/<area>` branch at a specific HEAD, in a specific worktree. Two parsing traps
were found by cross-checking against the real repositories, and both would have
sent a successor to the wrong tree:

- the tip is the **last** commit an area produced, not the first;
- `base <sha>` is where the area branched *from* — only an explicit `HEAD <sha>`
  can be trusted as the tip.

Without this the brief says "round 3 is still running, reviewing X". With it the
brief says "4 accepted, 1 rejected, 1 killed by the weekly limit, Integrate never
reached — and here is the branch, HEAD and worktree for each accepted area".

**Acceptance criteria.** The script calls
``agent(`<prompt>`, { label, phase: '<Name>', schema })``, so the definition of
"done" for the next phase is in that template literal. `phase_criteria` pulls it
for the first unreached phase, strips `${...}` interpolations (they reference
in-run state that means nothing outside it), and shows it under **Done when**.
That is the difference between "Integrate is next" and knowing that Integrate
means: branch `accel-sets3`, merge the accepted commits, build `s3_all`/`s3_all_g`,
FULL GATES vs REF at 0 diff, cachegrind for all 10 sets, state/name for the 6,
wall 5×ABAB.

**What it still cannot do.** `AGENT_DIED … resume this run` is Claude Code's own
Workflow capability; no other agent has it. So a cross-agent takeover is not
"resume that run" but "do the remaining phase from the artifacts". The brief
therefore has to carry the artifacts *and* the acceptance criteria, not just the
instruction.

### Non-goals

Not a recap of the session, and not an evaluation of it. It is a *triage line*:
enough to decide whether to resume this session or that one. A session that died
on a quota error and produced nothing is reported as such — that is information,
not a gap to be filled with invention.

---

## Suppressing dead sessions

Some sessions open, write one prompt, die, and leave nothing: no title, no
intent, no progress, no command. They cannot be deleted — the transcript belongs
to the agent — but they can stop being shown, which is the part that mattered.

`hidden.json` holds ``{short_id: {at, why}}``. `recent_sessions` filters it;
`am sessions`, `am brief` and the dashboard all inherit the filter, so there is
one place to change your mind. `am prune --sessions` finds the ones with all four
digest fields empty and hides them; `am hide <id> --undo` brings one back.

This is deliberately **not** deletion. Hiding is reversible in one command and
never touches the agent's own files, so a wrong hide costs nothing — whereas a
wrong delete costs the session.

## Dashboard performance

`state_payload` walks up to 20 sessions per request, and a single session can be
150 MB. Two caches keep polling cheap:

| cache | key | why |
|---|---|---|
| `DASHBOARD_CACHE` | whole payload, 3 s | a browser poll must not trigger a scan |
| `DIGEST_CACHE` | `(path, mtime)` | a session that has not changed is never re-digested |

Measured: 0.44 s cold, 0.01 s warm, 0.04 s after the payload cache expires but
the digest cache still hits. Without `DIGEST_CACHE` the first request timed out
before the page could render — the feature was unusable, not merely slow.

---

## Growth and retention

Measured on this machine, the store is **42 MB, of which 40 MB is the vector
index** — and that index is a rebuildable cache with a fixed 30-day window. The
rest is noise:

| part | now | growth |
|---|---|---|
| `idx/` | 39.8 MB | bounded by window, rebuildable |
| `tail/` | 906 KB | bounded, 400 lines per agent, rotated |
| `journal/` | 15 KB | ~2 MB/year at current rates |
| `tasks/` | 2 KB | linear in tasks ever created |
| **transcripts** | **1.5 GB** | grows fast — **not owned by `am`** |

So the store does not have a size problem; it has a **readability** problem: a
thousand finished task records turn `task list` and the overview into noise long
before disk matters.

### The rule

**Never delete what cannot be rebuilt.** Transcripts belong to the agents and are
never touched. Inside the store, only the journal and finished task records are
irreplaceable; `idx`, `tail` and `briefs` are caches or regenerable. So the
journal and finished tasks are *archived*, not dropped.

### `am prune`

Dry run by default — it prints the size breakdown first, then the plan, and does
nothing without `--yes`. Retention defaults to `retention_days` (90).

| What | Where it goes |
|---|---|
| `done` tasks older than the window | `archive/tasks/tasks-<YYYY-MM>.jsonl.gz`, one JSON per line, month taken from the task's own `updated` |
| journal shards older than the window | `archive/journal/<name>.jsonl.gz` |
| briefs older than the window | `archive/briefs/<name>.md` (plain, they are small and worth reading) |

Archives append a **new gzip member** rather than rewriting, so the cost is
proportional to what is added and earlier members stay readable through a plain
`gzip.open(...).read()`.

`am task list` hides finished tasks unless `--all` is given, so the everyday view
does not depend on having run a prune.

---

## Dashboard

`am serve` runs a `ThreadingHTTPServer` (stdlib only) with two routes: `/` serves
one self-contained page, `/api/state` serves the snapshot it polls. The page
re-fetches every 2.5 s, so neither switching the driving agent nor a task moving
requires a reload.

**It is a view, never a store.** Nothing renders to disk; the payload is built
from the same `load_tasks` / `read_lease` / `recent_sessions` / `workflow_digest`
calls the CLI uses, and cached for 3 s so a browser poll cannot turn into a scan
storm. `watch_scan` inside it is throttled to once a minute.

**Who is the main agent.** Sessions with transcript activity in the last 5
minutes are active; among those, one holding a live task lease wins; otherwise
the freshest active session. Liveness is transcript mtime, never a status field —
the same rule that caught the watchdog claiming `running` for three days.

**Everything in the window, not a fixed page.** The payload used to take the
newest N sessions, so hiding one pulled the next-oldest into view — a bug that
made hiding feel like pagination. It now returns every session inside
`dashboard_days` (default 30), and hiding simply removes one row.

**Subagent transcripts are not sessions.** `~/.claude/projects` currently holds
1250 files under `<session>/subagents/` against 10 top-level sessions. Including
them produced 292 "sessions" in a 30-day window and a 6 s cold payload. They are
filtered out by path segment.

**Interaction.** The sidebar is the index (searchable, grouped by agent,
collapsible, keyboard-navigable with `/` and `↑↓`, `p` pauses polling); the pane
is either the summary or one session's detail. Selection and expand state live in
the client, and a redraw restores them, so polling never collapses what you just
opened.

**Destructive actions require a trusted gesture.** The hide button checks
`e.isTrusted` before POSTing: during headless screenshot runs synthetic clicks
were silently hiding four real sessions, which is exactly the class of bug that
makes a tool untrustworthy.

Binds `127.0.0.1` by default. `--host 0.0.0.0` exposes it on the LAN, which
leaks task titles and reasoning to anyone who can reach the port — a deliberate
opt-in, not a default.

---

## Runbook: switching agents when quota runs out

```bash
# 1. In the dying agent, if you still can (optional — the transcript scan
#    already recorded what you ran):
am next "<the exact command you would run next>"
am log blocker "<what is unfinished>"
am log decision "<anything a successor must not reverse>"

# 2. When it dies, in the shell:
~/.agents/bin/am handoff --to codex

# 3. In the new agent, the first thing it does:
~/.agents/bin/am brief --for codex
~/.agents/bin/am claim <id> --force
# ... work ...
~/.agents/bin/am next "<next command>"
~/.agents/bin/am log result "<what now works>" --evidence "<test output>"

# 4. When the original agent comes back:
~/.agents/bin/am brief --for claude-code   # shows the successor's tail
```

Step 1 is best-effort. Steps 2–4 depend on nothing that step 1 wrote, because
`brief` and `handoff` run an incremental transcript scan first (see *Capture*
above). If the dying agent never touched `am`, the brief still shows its last
commands and says outright that transcript activity exists after the last
recorded event.

---

## Concurrency

- Journal appends are to per-agent files, so two agents never write the same file.
- Each append is a single `write()` of one line under `O_APPEND`; a concurrent
  reader skips an unparseable trailing line rather than crashing.
- `state.md` and `tail/*.jsonl` are written through a temp file + `os.replace`,
  so they are never torn.
- Ownership is a lease, not a lock: `claim --ttl`, and another agent may
  `--force` when the holder is dead or expired. There is no fcntl lock because
  agent processes die without releasing them.

## Security

A journal is a new instruction-injection surface: text one agent writes gets
read by another agent *as context*. Mitigations already in place:

- Every brief opens with an explicit "this is data, not instruction" preamble.
- The transcript block is labelled **"actions, not conclusions"**, so a scraped
  command can never read as a directive.
- `goal` is the only field taken near-verbatim into the brief, and it is a
  single sentence.
- Nothing from `~/.bitebit_env`, credentials, or tokens belongs in the journal.
  Transcript scraping copies commands verbatim, so a secret typed on the command
  line *will* land in `tail/` — never put one there.
- Briefs are read-only renders; only `am` writes state.

## Deliberately out of scope

- No MCP wrapper. The CLI works everywhere, including agents that do not exist
  yet; MCP would only re-expose the same commands to the agents that already
  have a shell. Add it if a future agent lacks filesystem access.
- No cross-encoder reranking. `--smart` is bi-encoder retrieval only: it finds
  conceptually near passages but cannot score a query-document pair jointly the
  way a reranker would. Add it only if `--min-score` tuning proves insufficient.
- No quota polling or automatic agent launching. Detecting three vendors' quota
  errors is brittle and saves one keystroke; the expensive part is rebuilding
  context, and that is what the brief solves.
- No cross-project aggregation. One `~/.agents/` per repo for now.
- No `journal/`, `tail/`, `.watch.json`, `idx/` in version control. They are
  machine state; a merged journal is a lie, and the vector index is a cache that
  `am embed` rebuilds. (`briefs/` is fine to commit if you want an audit trail of
  what each successor was told.)
