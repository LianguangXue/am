# Portable installation and dashboard performance review

The installation fixes and dashboard mitigations in this branch were prompted
by a Linux installation with custom agent configuration roots and large existing
transcripts. No user transcripts or machine-specific paths are included here.

## Reproduced problems

- `init --link` accepted the flag but never wrote `~/.am-root`, so commands from
  outside the project could not discover the store.
- Transcript roots ignored `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, and `DSH_HOME`.
- Equivalent project paths reached through symlinks could fail scope matching.
- A title-free transcript could make digest extraction walk much of its history.
  Initial watch ingestion also read the entire plain transcript into memory.
- Simultaneous dashboard requests could rebuild the same uncached snapshot.

## Proposed changes and review boundaries

Installation now honors the three configuration variables, normalizes scope
paths, and implements the global pointer. Regression tests use temporary homes
and stores, including invocation from outside the initialized project.

The dashboard changes are provisional performance mitigations: plain transcript
digests and initial observation ingestion use a recent approximately 2 MB window;
GET snapshot generation is serialized and snapshots are cached for 15 seconds
after construction finishes. Existing observations and source transcripts are
not deleted or rewritten.

The recent window changes completeness: older titles, narration, and commands
may be absent, and a complete record overlapping the bootstrap boundary is
skipped. An incomplete overlapping record does not advance the cursor. A single
large line can still exceed the nominal read window during alignment or opening
prompt extraction. Compressed DSH logs still require full decompression. These
changes therefore do not establish a strict global memory or latency bound.

Before adopting this as a final indexing design, consider persistent incremental
metadata/digests, byte-bounded record handling, file rotation and truncation,
background snapshot refresh, and less frequent source-directory discovery on
shared filesystems. Hiding a session does not currently invalidate the snapshot
cache immediately, so the longer cache can delay that UI update.

## Measurements and validation

On the observed installation, the original real-data state request exceeded
50 seconds. With the local mitigations, the initial request completed in 20.22
seconds and a subsequent request in 0.35 seconds. The payload showed 400 recent
sessions across the three providers. These are single-machine observations,
not a controlled benchmark or a cross-platform performance guarantee.

Run `bash tests/smoke.sh` and `python3 tests/stdlib_only.py`. The smoke suite also
runs `tests/portability.py`, covering configuration roots, link fallback, symlink
scope, missing transcripts, bootstrap bounds, partial records, incremental
cursors, and recent digest extraction without a title.

Dashboard scope remains the most recent 30 days with a 400-session cap by
default. Active status is inferred from transcript modification time rather
than confirmed process liveness. Browser rendering and provider account-profile
aggregation are outside these regression checks.
