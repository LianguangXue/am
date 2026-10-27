#!/usr/bin/env bash
# End-to-end smoke test for `am`.
#
# Runs against a throwaway store in a temp directory: no access to the caller's
# real memory, no network, no third-party packages. Every check asserts on
# observable behaviour, so it stays valid if the internals are rewritten.
#
# Usage:  bash tests/smoke.sh [path-to-am]
#         TMPDIR=/somewhere bash tests/smoke.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AM="${1:-$REPO/bin/am}"
WORK="$(mktemp -d)"
SRV=""

cleanup() {
  [ -n "$SRV" ] && kill "$SRV" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

fail() { printf 'FAIL  %s\n' "$*" >&2; exit 1; }
ok()   { printf 'ok    %s\n' "$*"; }

[ -x "$AM" ] || fail "not executable: $AM"
[ -f "$REPO/templates/AGENTS-entry.md" ] || fail "missing entry template"

# ---------------------------------------------------------------- binary
"$AM" --version | grep -q '^am ' || fail "--version"
"$AM" --help >/dev/null || fail "--help"
python3 -m py_compile "$REPO/bin/am" "$REPO/bin/am-embed.py"
python3 "$REPO/tests/stdlib_only.py" >/dev/null || {
  python3 "$REPO/tests/stdlib_only.py"; fail "the core tool must stay stdlib-only"; }
ok "binary runs, byte-compiles and is stdlib-only"
python3 "$REPO/tests/portability.py"

# ---------------------------------------------------------------- init
cd "$WORK"
"$AM" init --project ci >/dev/null
[ -f .agents/config.json ] || fail "init did not create a store"
[ -f .agents/DESIGN.md ]   || fail "init did not ship DESIGN.md into the store"
ok "init creates a self-describing store"

cp "$REPO/templates/AGENTS-entry.md" AGENTS.md
cp "$REPO/templates/AGENTS-entry.md" CLAUDE.md
ok "entry stanzas installed"

# ---------------------------------------------------------------- work
"$AM" --agent codex goal "ship the thing" >/dev/null
"$AM" --agent codex start demo --accept "tests pass" >/dev/null
"$AM" --agent codex next "pytest -x tests/" >/dev/null
"$AM" --agent codex log decision "chose A because it is faster" >/dev/null
ok "goal, task and events recorded"

"$AM" doctor >/dev/null 2>&1 || { "$AM" doctor; fail "doctor reported problems"; }
ok "doctor is clean"

# ---------------------------------------------------------------- brief
BRIEF="$("$AM" brief --for dsh)"
printf '%s' "$BRIEF" | grep -q 'pytest -x tests/' || fail "brief lost the declared next step"
printf '%s' "$BRIEF" | grep -q 'tests pass'      || fail "brief lost the acceptance criterion"
printf '%s' "$BRIEF" | grep -q 'chose A'         || fail "brief lost the decision"
ok "brief carries goal, task, next step and decision"

# The brief must never be mistaken for an instruction from the user.
printf '%s' "$BRIEF" | grep -qi 'data, not instruction' || fail "brief lost its data-not-instruction banner"
ok "brief is fenced as data"

# ---------------------------------------------------------------- zh
ZH="$("$AM" --lang zh brief --for dsh)"
printf '%s' "$ZH" | grep -q '交接简报' || fail "--lang zh did not switch the brief"
printf '%s' "$ZH" | grep -q '不是指令' || fail "--lang zh did not switch the safety banner"
ok "--lang zh"

# ---------------------------------------------------------------- takeover
"$AM" --agent claude-code claim demo --force >/dev/null || fail "forced claim failed"
ok "a dead lease can be taken over"

# ---------------------------------------------------------------- recall
"$AM" recall "chose A" >/dev/null 2>&1 || fail "recall failed"
ok "literal recall"

# ---------------------------------------------------------------- prune
"$AM" prune >/dev/null || fail "prune dry run failed"
[ -d .agents/tasks ] || fail "prune dry run removed the task directory"
ok "prune defaults to a dry run"

# ---------------------------------------------------------------- dashboard
PORT=$(( 37800 + ($$ % 200) ))
"$AM" serve --port "$PORT" >/dev/null 2>&1 &
SRV=$!
for _ in $(seq 1 40); do
  curl -fsS "http://127.0.0.1:$PORT/api/state" >/dev/null 2>&1 && break
  sleep 0.25
done
curl -fsS "http://127.0.0.1:$PORT/api/state" >/dev/null || fail "dashboard API did not answer"
# Capture before matching: `curl | grep -q` under `pipefail` reports the SIGPIPE
# that grep causes by exiting early, which looks like a failure but is not.
curl -fsS "http://127.0.0.1:$PORT/" -o "$WORK/page.html" || fail "dashboard page did not load"
# The page is a shell that fetches state at runtime, so assert on the shell and
# on the substitution of the project name rather than on rendered text.
grep -q 'id="pane"' "$WORK/page.html" || fail "dashboard page did not render"
! grep -q '__PROJECT__' "$WORK/page.html" || fail "dashboard did not substitute the project name"
ok "dashboard serves state and page"

# Bulk suppression is what the dashboard's multi-select posts to; the ids do not
# have to correspond to real sessions for the endpoint contract to be checked.
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"shorts":["smoke-a","smoke-b"]}' "http://127.0.0.1:$PORT/api/hide" -o "$WORK/hide.json" \
  || fail "bulk hide endpoint"
grep -q 'smoke-a' "$WORK/hide.json" || fail "bulk hide did not record the ids"
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"shorts":["smoke-a","smoke-b"],"undo":true}' "http://127.0.0.1:$PORT/api/hide" -o "$WORK/undo.json" \
  || fail "bulk restore endpoint"
grep -q 'smoke-a' "$WORK/undo.json" && fail "bulk restore left an id behind"
ok "bulk hide and restore"

printf '\nall checks passed\n'
