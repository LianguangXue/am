#!/usr/bin/env bash
# Link `am` onto PATH and make the scripts executable. Safe to re-run.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${AM_BIN_DIR:-$HOME/.local/bin}"

chmod +x "$REPO/bin/am" "$REPO/bin/am-embed.py"
mkdir -p "$DEST"
ln -sf "$REPO/bin/am" "$DEST/am"

echo "linked  $DEST/am -> $REPO/bin/am"
case ":$PATH:" in
  *":$DEST:"*) ;;
  *) echo "note    $DEST is not on your PATH — add it to your shell rc" ;;
esac

echo
echo "next:"
echo "  1. cd into the project you want the memory to cover"
echo "  2. am init --project <name> --link     # creates ./.agents and ~/.am-root"
echo "  3. paste templates/AGENTS-entry.md into AGENTS.md and CLAUDE.md"
echo "  4. am doctor                            # checks the wiring"
echo
echo "optional:"
echo "  am serve                                # live dashboard on :37778"
