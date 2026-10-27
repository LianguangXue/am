#!/usr/bin/env python3
"""Disposable regression checks for portable installation and large transcripts."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "bin/am"
LOADER = importlib.machinery.SourceFileLoader("am_portability", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
AM = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(AM)


def command(text: str) -> bytes:
  """Encode a Claude command record for a disposable transcript."""
  return (json.dumps({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Bash", "input": {"command": text}},
  ]}}) + "\n").encode()


class PortabilityTests(unittest.TestCase):
  """Exercise installation boundaries without reading real agent stores."""

  def test_source_roots(self) -> None:
    """Honor custom roots and fall back for missing or empty variables."""
    with tempfile.TemporaryDirectory() as directory:
      home = Path(directory)
      with patch.object(AM.Path, "home", return_value=home), patch.dict(os.environ, {}, clear=True):
        self.assertEqual([row[1] for row in AM.transcript_sources()], [
          home / ".claude/projects", home / ".codex/sessions", home / ".dsh/sessions",
        ])
        os.environ.update(CLAUDE_CONFIG_DIR="~/claude-profile", CODEX_HOME=str(home / "codex-profile"),
                          DSH_HOME=str(home / "dsh-profile"), HOME=str(home))
        self.assertEqual([row[1] for row in AM.transcript_sources()], [
          home / "claude-profile/projects", home / "codex-profile/sessions", home / "dsh-profile/sessions",
        ])
        os.environ["CODEX_HOME"] = ""
        self.assertEqual(AM.transcript_sources()[1][1], home / ".codex/sessions")

  def test_link_from_outside_project(self) -> None:
    """The real CLI writes a pointer usable from an unrelated directory."""
    with tempfile.TemporaryDirectory() as directory:
      home = Path(directory)
      project = home / "project"
      outside = home / "outside"
      project.mkdir()
      outside.mkdir()
      env = dict(os.environ, HOME=str(home))
      env.pop("AM_ROOT", None)
      subprocess.run([sys.executable, str(SCRIPT), "init", "--project", "fixture", "--link"],
                     cwd=project, env=env, check=True, capture_output=True)
      expected = str((project / ".agents").resolve())
      self.assertEqual((home / ".am-root").read_text().strip(), expected)
      result = subprocess.run([sys.executable, str(SCRIPT), "where"], cwd=outside, env=env,
                              check=True, capture_output=True, text=True)
      self.assertEqual(result.stdout.strip(), expected)

  def test_symlink_scope(self) -> None:
    """Canonical aliases match while similarly prefixed siblings do not."""
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory) / "project"
      root.mkdir()
      alias = Path(directory) / "alias"
      alias.symlink_to(root, target_is_directory=True)
      with patch.object(AM, "transcript_cwd", return_value=str(alias)):
        self.assertTrue(AM.session_in_scope("codex", Path("session.jsonl"), root, "no-slug-match"))
      with patch.object(AM, "transcript_cwd", return_value=str(root) + "-sibling"):
        self.assertFalse(AM.session_in_scope("codex", Path("session.jsonl"), root, "no-slug-match"))

  def test_large_bootstrap_and_incremental_cursor(self) -> None:
    """Bootstrap is bounded and appended complete commands appear exactly once."""
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "session.jsonl"
      path.write_bytes((b'{"padding":"' + b'x' * 1000 + b'"}\n') * 3000 + command("recent"))
      with patch.object(AM, "read_tail_lines", wraps=AM.read_tail_lines) as reader:
        rows, offset = AM._scan_plain(path, "claude-code", 0)
        self.assertGreater(reader.call_args.args[1], 0)
        self.assertLessEqual(path.stat().st_size - reader.call_args.args[1], 2_000_000)
      self.assertEqual([row["text"] for row in rows], ["recent"])
      pending = command("appended")
      with path.open("ab") as handle:
        handle.write(pending[:-1])
      self.assertEqual(AM._scan_plain(path, "claude-code", offset), ([], offset))
      with path.open("ab") as handle:
        handle.write(b"\n")
      rows, offset = AM._scan_plain(path, "claude-code", offset)
      self.assertEqual([row["text"] for row in rows], ["appended"])
      self.assertEqual(AM._scan_plain(path, "claude-code", offset), ([], offset))

  def test_missing_and_oversized_partial_record(self) -> None:
    """Missing files are harmless and incomplete bootstrap records retain the cursor."""
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "session.jsonl"
      self.assertEqual(AM._scan_plain(path, "claude-code", 0), ([], 0))
      path.write_bytes(b'{"padding":"' + b'x' * 2_100_000)
      self.assertEqual(AM._scan_plain(path, "claude-code", 0), ([], 0))
      with path.open("ab") as handle:
        handle.write(b'"}\n' + command("after-completion"))
      rows, offset = AM._scan_plain(path, "claude-code", 0)
      self.assertEqual([row["text"] for row in rows], ["after-completion"])
      self.assertEqual(offset, path.stat().st_size)

  def test_recent_digest_without_title(self) -> None:
    """A title-free transcript still exposes recent progress and commands."""
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "session.jsonl"
      progress = "The latest verification completed successfully and the next change is ready for review."
      records = [
        {"type": "user", "message": {"content": "Please validate this disposable fixture"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": progress}]}},
      ]
      path.write_bytes(b''.join((json.dumps(row) + "\n").encode() for row in records) + command("verify"))
      with patch.object(AM, "iter_lines_reversed", side_effect=AssertionError("unbounded digest")):
        digest = AM.session_digest("claude-code", path)
      self.assertEqual(digest["progress"], progress)
      self.assertEqual(digest["action"], "verify")


if __name__ == "__main__":
  unittest.main()
