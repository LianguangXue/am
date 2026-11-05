"""Standalone am protocol checks; no delegate installation or real store needed."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

API = runpy.run_path(str(Path(__file__).resolve().parents[1] / "bin/am"))


class ProtocolTests(unittest.TestCase):
  def test_conflicting_scoped_summaries_do_not_claim_acceptance(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      target = root / "integrations/delegate/task"
      target.mkdir(parents=True)
      (target / "index.json").write_text('["a","b"]')
      for source, review in (("a", "accepted"), ("b", "needs-work")):
        (target / (source + ".json")).write_text(json.dumps({"session_id": "s", "jobs": [
          {"id": "j", "status": "completed", "review": review, "collected_at": 1}]}))
      result = API["delegate_summary"](root, "task")
      self.assertEqual(result["conflicting"], 1)
      self.assertEqual(result["accepted"], 0)

  def test_stale_and_duplicate_imports_never_roll_back_or_complete_task(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      (root / "tasks").mkdir()
      (root / "tasks/task.json").write_text('{"id":"task","status":"open"}')
      packet = {"schema_version": 1, "source_id": "source", "session_id": "session",
                "am_task_id": "task", "revision": 2, "jobs": []}
      for revision in (2, 2, 1):
        with patch("sys.stdin", io.StringIO(json.dumps({**packet, "revision": revision}))), contextlib.redirect_stdout(io.StringIO()):
          self.assertEqual(API["cmd_delegate"](root, {}, argparse.Namespace(action="import")), 0)
      rows = API["delegate_packets"](root, "task")
      self.assertEqual(len(rows), 1)
      self.assertEqual(rows[0]["revision"], 2)
      self.assertEqual(json.loads((root / "tasks/task.json").read_text())["status"], "open")
      with patch("sys.stdin", io.StringIO(json.dumps({**packet, "next_step": "conflict"}))), contextlib.redirect_stderr(io.StringIO()):
        with self.assertRaises(SystemExit):
          API["cmd_delegate"](root, {}, argparse.Namespace(action="import"))


if __name__ == "__main__":
  unittest.main()
