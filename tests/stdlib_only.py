#!/usr/bin/env python3
"""Assert that `bin/am` imports nothing outside the standard library.

The core tool advertises "stdlib only" because it has to run on any machine a
coding agent happens to be on, with no install step. That promise decays the
moment someone adds an innocent `import requests`, so it is enforced here rather
than left in a README.

`bin/am-embed.py` is exempt: it is the optional semantic encoder, it lives in its
own venv, and it may import numpy / torch / sentence-transformers.
"""

from __future__ import annotations

import ast
import pathlib
import sys

TARGETS = ("bin/am",)


def imported_roots(path: pathlib.Path) -> set[str]:
  """Return the top-level module names a file imports at any depth."""
  tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
  roots: set[str] = set()
  for node in ast.walk(tree):
    if isinstance(node, ast.Import):
      roots.update(alias.name.split(".")[0] for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
      if node.level:          # relative import: not a third-party package
        continue
      if node.module:
        roots.add(node.module.split(".")[0])
  return roots


def main() -> int:
  if not hasattr(sys, "stdlib_module_names"):
    print("skip  sys.stdlib_module_names is unavailable before Python 3.10")
    return 0

  stdlib = set(sys.stdlib_module_names) | {"__future__"}
  failures = 0
  for name in TARGETS:
    path = pathlib.Path(name)
    if not path.is_file():
      print(f"FAIL  {name}: missing")
      failures += 1
      continue
    outside = sorted(imported_roots(path) - stdlib)
    if outside:
      print(f"FAIL  {name} imports outside the standard library: {', '.join(outside)}")
      failures += 1
    else:
      print(f"ok    {name} is stdlib-only")

  return 1 if failures else 0


if __name__ == "__main__":
  raise SystemExit(main())
